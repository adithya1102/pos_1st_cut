"""The stock-hold TTL: its value, its sweep, and what happens after it lapses.

migration 033 created `stock_reservations.expires_at` as NOT NULL but left the
TTL VALUE an open decision — the "existing payment-retry grace window" it was
meant to inherit does not exist in this codebase. It is now
STOCK_HOLD_TTL_SECONDS = 600.

What has to hold, and what each group here pins:

  1. the TTL is applied on insert and tracks the setting, in SECONDS;
  2. the sweep releases expired HELD rows and NOTHING else — not an unexpired
     hold, not a PAID one, not a COMMITTED one — and is idempotent, because it
     is called from read paths at whatever rate customers happen to generate;
  3. a payment that lands AFTER the sweep either re-acquires its units or
     cancels and flags a refund. Never oversells, never silently proceeds;
  4. the gateway order expires with the hold, so a live payment page is never
     backed by a lapsed reservation;
  5. one live unpaid hold per customer per outlet, or the TTL is a loophole
     rather than a limit.

These run against the LOCAL carevo_test with a real asyncpg pool.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.core.config import Settings, settings
from app.modules.carevo_customer.stock import COMMITTED, HELD, RELEASED
from tests.conftest import API
from tests.test_api_stock_reservation import (
    _customers, _place_one, _reservations, _set_stock, _stock,
)


# ------------------------------- helpers -------------------------------------

async def _expiry(db, order_id):
    return await db.scalar(text(
        "SELECT expires_at FROM stock_reservations WHERE order_id = :i"),
        {"i": str(order_id)})


async def _force_expired(db, order_id) -> None:
    """Backdate the hold. The only way to test a 600-second clock in 600ms."""
    await db.execute(text(
        "UPDATE stock_reservations SET expires_at = now() - interval '1 minute' "
        "WHERE order_id = :i"), {"i": str(order_id)})
    await db.commit()


async def _pay(client, seed, order_id, auth=None):
    return await client.post(f"{API}/customer/payment/simulate",
                             headers=auth or seed["customer_auth"],
                             json={"order_id": str(order_id), "method": "upi"})


async def _order_row(db, order_id):
    return (await db.execute(text(
        "SELECT status, payment_status, refund_required, refund_reason "
        "FROM customer_orders WHERE id = :i"), {"i": str(order_id)})).first()


# ======================== 1. the TTL is applied ==============================

@pytest.mark.asyncio
class TestTtlOnInsert:
    async def test_the_default_is_600_seconds(self):
        """Declared default, not the live value, so a local .env cannot change
        what CI asserts."""
        assert Settings.model_fields["STOCK_HOLD_TTL_SECONDS"].default == 600

    async def test_the_old_minutes_setting_is_gone(self):
        """It was STOCK_RESERVATION_TTL_MINUTES = 15 (900s). Leaving both would
        let a reader tune the dead one and see nothing change."""
        assert not hasattr(settings, "STOCK_RESERVATION_TTL_MINUTES")

    async def test_a_hold_expires_one_ttl_from_now(self, client, seed, db):
        await _set_stock(db, seed["menu_item_id"], 3)
        before = datetime.now(timezone.utc)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert r.status_code == 200, r.text

        at = await _expiry(db, r.json()["id"])
        assert at is not None, "expires_at is NOT NULL; a hold cannot lack one"
        delta = (at - before).total_seconds()
        # Generous lower bound, tight upper: the only failures worth catching
        # are "minutes were read as seconds" (would be 10) and "the value is
        # ignored" (would be 900, the old setting).
        assert 590 <= delta <= 615, (
            f"hold expires in {delta:.0f}s, expected ~"
            f"{settings.STOCK_HOLD_TTL_SECONDS}s")

    async def test_the_insert_tracks_the_setting(self, client, seed, db,
                                                 monkeypatch):
        """Changing the setting changes the stamp — i.e. nothing is hardcoded.

        Patched on the settings OBJECT that stock.py reads, which is the same
        singleton; a 60s value is far enough from 600 to be unambiguous.
        """
        monkeypatch.setattr(settings, "STOCK_HOLD_TTL_SECONDS", 60)
        await _set_stock(db, seed["menu_item_id"], 3)
        before = datetime.now(timezone.utc)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert r.status_code == 200, r.text

        delta = (await _expiry(db, r.json()["id"]) - before).total_seconds()
        assert 50 <= delta <= 75, f"expected ~60s, got {delta:.0f}s"


# ===================== 2. the sweep, and only the sweep ======================

@pytest.mark.asyncio
class TestSweep:
    async def test_it_releases_an_expired_held_row_and_returns_the_units(
            self, client, seed, db):
        from app.modules.carevo_customer.stock import StockService
        await _set_stock(db, seed["menu_item_id"], 3)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        assert await _stock(db, seed["menu_item_id"]) == 1
        await _force_expired(db, oid)

        assert await StockService.sweep_expired(db) >= 1
        assert await _stock(db, seed["menu_item_id"]) == 3
        assert [s for _, _, s in await _reservations(db, oid)] == [RELEASED]

    async def test_it_leaves_an_unexpired_hold_alone(self, client, seed, db):
        """The clock is the entire predicate; a live hold must survive it."""
        from app.modules.carevo_customer.stock import StockService
        await _set_stock(db, seed["menu_item_id"], 3)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]

        assert await StockService.sweep_expired(db) == 0
        assert await _stock(db, seed["menu_item_id"]) == 1
        assert [s for _, _, s in await _reservations(db, oid)] == [HELD]

    async def test_a_paid_order_is_never_released(self, client, seed, db):
        """Even with the clock run out. A paid hold is the restaurant's
        commitment and is released by a terminal transition, never by time.

        Both guards are exercised at once: the row is COMMITTED (not HELD) AND
        the order is PAID, and either alone is sufficient.
        """
        from app.modules.carevo_customer.stock import StockService
        await _set_stock(db, seed["menu_item_id"], 3)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        assert (await _pay(client, seed, oid)).status_code == 200
        await _force_expired(db, oid)

        assert await StockService.sweep_expired(db) == 0
        assert await _stock(db, seed["menu_item_id"]) == 1, \
            "a paid order's stock was reclaimed by the clock"
        assert [s for _, _, s in await _reservations(db, oid)] == [COMMITTED]

    async def test_it_is_idempotent(self, client, seed, db):
        """Called from read paths, so it runs as often as customers browse.

        A second pass must return the units ZERO extra times — the UPDATE's own
        WHERE clause is the mechanism, since the first pass moved the rows out
        of HELD.
        """
        from app.modules.carevo_customer.stock import StockService
        await _set_stock(db, seed["menu_item_id"], 3)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        await _force_expired(db, oid)

        first = await StockService.sweep_expired(db)
        after_first = await _stock(db, seed["menu_item_id"])
        second = await StockService.sweep_expired(db)
        third = await StockService.sweep_expired(db)

        assert first >= 1
        assert second == 0 and third == 0, \
            f"the sweep found rows again ({second}, {third}) — not idempotent"
        assert after_first == 3
        assert await _stock(db, seed["menu_item_id"]) == 3, \
            "units were returned more than once"
        assert [s for _, _, s in await _reservations(db, oid)] == [RELEASED]

    async def test_the_menu_read_triggers_it(self, client, seed, db):
        """Check-on-read: there is no worker, so a read path has to do it.

        get_menu is the frequently-hit one AND the one where a stale hold is
        visible — reserve_for_order flips is_available off at zero, so an
        abandoned cart makes a dish read sold out to everyone else.
        """
        await _set_stock(db, seed["menu_item_id"], 2)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        assert await _stock(db, seed["menu_item_id"]) == 0
        await _force_expired(db, oid)

        m = await client.get(f"{API}/customer/menu/{seed['outlet_id']}",
                             headers=seed["customer_auth"])
        assert m.status_code == 200, m.text

        assert await _stock(db, seed["menu_item_id"]) == 2, \
            "reading the menu did not reclaim a lapsed hold"
        items = [i for cat in m.json()["categories"] for i in cat["items"]
                 if i["id"] == seed["menu_item_id"]]
        assert items and items[0]["is_available"] is True, \
            "the dish is still marked sold out after its hold lapsed"

    async def test_order_creation_triggers_it(self, client, seed, db):
        """So the stock being reserved against is current.

        The second customer's order can only succeed if the first customer's
        lapsed hold was reclaimed inside that same transaction.
        """
        await _set_stock(db, seed["menu_item_id"], 1)
        first = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert first.status_code == 200
        assert await _stock(db, seed["menu_item_id"]) == 0
        await _force_expired(db, first.json()["id"])

        other = (await _customers(db, 1))[0]
        second = await _place_one(client, seed, seed["menu_item_id"], qty=1,
                                  auth=other)
        assert second.status_code == 200, (
            "the lapsed hold was not reclaimed at order creation: "
            f"{second.status_code} {second.text}")
        assert await _stock(db, seed["menu_item_id"]) == 0


# ==================== 3. payment landing after the sweep =====================

@pytest.mark.asyncio
class TestLatePayment:
    async def test_it_commits_an_expired_hold_that_was_never_swept(
            self, client, seed, db):
        """Minute 10 to minute 16 — the window the Cashfree floor creates.

        The hold is 600s and Cashfree refuses any expiry inside 15 minutes, so
        the payment page necessarily outlives the hold by ~6 minutes. A
        customer paying in that gap arrives with `expires_at` in the past and
        the row STILL `HELD`, because the sweep is check-on-read and nothing
        has read since.

        This is the COMMON case in that window and it is uneventful:
        `rereserve_for_order` finds no RELEASED rows and short-circuits to True
        (stock.py:243-245), so `commit_for_order` commits the hold the customer
        has had all along. Nothing is re-taken because nothing was given back,
        and stock is unchanged from the moment of ordering.

        The two tests below are the other half — what happens once a sweep HAS
        run. Together they cover both sides of the gap.
        """
        await _set_stock(db, seed["menu_item_id"], 5)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        assert await _stock(db, seed["menu_item_id"]) == 3

        # Past its expiry, and deliberately NOT swept.
        await _force_expired(db, oid)
        assert [s for _, _, s in await _reservations(db, oid)] == [HELD]

        assert (await _pay(client, seed, oid)).status_code == 200

        row = await _order_row(db, oid)
        assert row.payment_status == "PAID"
        assert row.status != "CANCELLED", \
            "an unswept expired hold was treated as lost stock"
        assert row.refund_required is False
        assert [s for _, _, s in await _reservations(db, oid)] == [COMMITTED]
        assert await _stock(db, seed["menu_item_id"]) == 3, \
            "stock moved for units that were never released"

    async def test_it_re_acquires_when_the_units_are_still_there(
            self, client, seed, db):
        """The hold lapsed, nobody else took the units, then the money landed.

        The order proceeds and the reservation ends COMMITTED — the customer is
        fed and nothing is oversold.
        """
        await _set_stock(db, seed["menu_item_id"], 5)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        await _force_expired(db, oid)

        from app.modules.carevo_customer.stock import StockService
        assert await StockService.sweep_expired(db) >= 1
        assert await _stock(db, seed["menu_item_id"]) == 5

        assert (await _pay(client, seed, oid)).status_code == 200
        row = await _order_row(db, oid)
        assert row.payment_status == "PAID"
        assert row.status != "CANCELLED", "a recoverable order was cancelled"
        assert row.refund_required is False
        assert [s for _, _, s in await _reservations(db, oid)] == [COMMITTED]
        assert await _stock(db, seed["menu_item_id"]) == 3, \
            "the re-acquired units were not taken out of stock again"

    async def test_it_flags_a_refund_when_the_units_are_gone(
            self, client, seed, db):
        """The hold lapsed, SOMEBODY ELSE took the units, then the money landed.

        The one outcome worse than a refund is promising food that does not
        exist, so the order is cancelled and flagged rather than confirmed.
        """
        await _set_stock(db, seed["menu_item_id"], 2)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        await _force_expired(db, oid)

        from app.modules.carevo_customer.stock import StockService
        assert await StockService.sweep_expired(db) >= 1
        # Another customer takes everything that just came back.
        other = (await _customers(db, 1))[0]
        taken = await _place_one(client, seed, seed["menu_item_id"], qty=2,
                                 auth=other)
        assert taken.status_code == 200, taken.text
        assert await _stock(db, seed["menu_item_id"]) == 0

        assert (await _pay(client, seed, oid)).status_code == 200
        row = await _order_row(db, oid)
        assert row.status == "CANCELLED", \
            "an order was confirmed with no stock behind it"
        assert row.refund_required is True
        assert row.refund_reason == "stock_gone_after_payment"
        # The other customer keeps their units: no oversell, ever.
        assert await _stock(db, seed["menu_item_id"]) == 0
        assert [s for _, _, s in await _reservations(db, oid)] == [RELEASED]

        # An order_event, so the refund is reconstructable from the log rather
        # than only from a boolean column. order_events is append-only, which
        # makes it the durable record of WHY money is owed.
        events = (await db.execute(text(
            "SELECT event_type, payload FROM order_events "
            " WHERE order_id = :i AND event_type = 'ORDER_REJECTED'"),
            {"i": str(oid)})).fetchall()
        assert events, "no ORDER_REJECTED event recorded for the refund"
        payloads = [e.payload for e in events]
        assert any(
            (p or {}).get("reason") == "stock_gone_after_payment"
            for p in payloads), f"event payloads do not say why: {payloads}"

    async def test_it_never_oversells_even_when_both_outcomes_are_possible(
            self, client, seed, db):
        """Two lapsed orders, one unit back. Exactly one may be re-acquired."""
        await _set_stock(db, seed["menu_item_id"], 1)
        a = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert a.status_code == 200
        await _force_expired(db, a.json()["id"])

        other = (await _customers(db, 1))[0]
        b = await _place_one(client, seed, seed["menu_item_id"], qty=1,
                             auth=other)
        assert b.status_code == 200, b.text
        await _force_expired(db, b.json()["id"])

        from app.modules.carevo_customer.stock import StockService
        await StockService.sweep_expired(db)
        assert await _stock(db, seed["menu_item_id"]) == 1

        assert (await _pay(client, seed, a.json()["id"])).status_code == 200
        assert (await _pay(client, seed, b.json()["id"], auth=other)).status_code == 200

        rows = [await _order_row(db, a.json()["id"]),
                await _order_row(db, b.json()["id"])]
        confirmed = [r for r in rows if r.status != "CANCELLED"]
        refunded = [r for r in rows if r.refund_required]
        assert len(confirmed) == 1, \
            f"{len(confirmed)} orders confirmed against 1 unit — oversold"
        assert len(refunded) == 1
        assert await _stock(db, seed["menu_item_id"]) == 0

    async def test_a_replayed_payment_is_idempotent(self, client, seed, db):
        """The gateway retries until it gets a 200, so replays are routine.

        A second delivery must not move stock again, must not re-commit, and
        must leave the order exactly as the first one left it.
        """
        await _set_stock(db, seed["menu_item_id"], 5)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]

        assert (await _pay(client, seed, oid)).status_code == 200
        first = await _order_row(db, oid)
        stock_after_first = await _stock(db, seed["menu_item_id"])

        for _ in range(3):
            assert (await _pay(client, seed, oid)).status_code == 200

        assert await _stock(db, seed["menu_item_id"]) == stock_after_first, \
            "a replayed payment moved stock again"
        assert [s for _, _, s in await _reservations(db, oid)] == [COMMITTED]
        again = await _order_row(db, oid)
        assert (again.status, again.payment_status, again.refund_required) == \
               (first.status, first.payment_status, first.refund_required)

    async def test_a_replay_after_the_refund_path_does_not_resurrect_it(
            self, client, seed, db):
        """The nastiest replay: the first delivery cancelled + flagged a refund.

        A second must not flip that order back to live. mark_paid's terminal
        guard is what stops it, and without this the customer would be told
        their refunded order is being cooked.
        """
        await _set_stock(db, seed["menu_item_id"], 1)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        oid = r.json()["id"]
        await _force_expired(db, oid)

        from app.modules.carevo_customer.stock import StockService
        await StockService.sweep_expired(db)
        other = (await _customers(db, 1))[0]
        assert (await _place_one(client, seed, seed["menu_item_id"], qty=1,
                                 auth=other)).status_code == 200

        assert (await _pay(client, seed, oid)).status_code == 200
        assert (await _order_row(db, oid)).status == "CANCELLED"

        for _ in range(2):
            await _pay(client, seed, oid)
        row = await _order_row(db, oid)
        assert row.status == "CANCELLED", "a refunded order was resurrected"
        assert row.refund_required is True
        assert await _stock(db, seed["menu_item_id"]) == 0


# ==================== 4. the gateway expires with the hold ===================

class TestGatewayExpiryAlignment:
    """Cashfree's floor is SIXTEEN minutes here, not five.

    Their payment-lifecycle page says "Set order expiry time: Minimum 5
    minutes, maximum 30 days". The live API does not agree, and said so in
    production:

        {"code":"order_expiry_time_invalid",
         "message":"order_expiry_time : Expiry time should be more than 15 min
                    and less than 30 days"}

    The old 300 floor was taken from that page, STOCK_HOLD_TTL_SECONDS is 600,
    600 > 300 — so the clamp never fired and every single checkout was refused.
    These tests assert against the ERROR, which is the authority, with a minute
    of margin on each strict inequality (960s / 29 days).
    """

    def test_the_floor_is_sixteen_minutes_not_five(self):
        from app.modules.carevo_payments.gateway import CashfreeGateway
        assert CashfreeGateway.MIN_ORDER_EXPIRY_SECONDS == 960
        assert CashfreeGateway.MAX_ORDER_EXPIRY_SECONDS == 29 * 24 * 60 * 60

    @pytest.mark.parametrize("ttl", [60, 600, 960])
    def test_a_ttl_at_or_below_the_floor_is_raised_to_it(self, ttl, monkeypatch):
        """600 is the LIVE production value and the one that was failing — a
        TTL does not have to be unreasonably short to be refused."""
        from app.modules.carevo_payments.gateway import CashfreeGateway
        monkeypatch.setattr(settings, "STOCK_HOLD_TTL_SECONDS", ttl)
        assert CashfreeGateway.expiry_seconds() == 960

    def test_a_ttl_above_the_floor_is_sent_unchanged(self, monkeypatch):
        """Past the floor the hold and the payment page line up exactly, which
        is the behaviour the clamp exists to preserve where it can."""
        from app.modules.carevo_payments.gateway import CashfreeGateway
        monkeypatch.setattr(settings, "STOCK_HOLD_TTL_SECONDS", 3600)
        assert CashfreeGateway.expiry_seconds() == 3600

    def test_an_absurd_ttl_is_capped_at_29_days(self, monkeypatch):
        """The other end of the same sentence. Unreachable today — nothing
        sets a TTL in months — so this guards a future value, not a live one."""
        from app.modules.carevo_payments.gateway import CashfreeGateway
        monkeypatch.setattr(settings, "STOCK_HOLD_TTL_SECONDS", 90 * 24 * 60 * 60)
        assert CashfreeGateway.expiry_seconds() == 29 * 24 * 60 * 60

    def test_the_production_ttl_clears_the_floor_on_the_wire(self):
        """The regression itself, stated as the customer experiences it: with
        the real STOCK_HOLD_TTL_SECONDS, is the timestamp we send acceptable?"""
        from app.modules.carevo_payments.gateway import CashfreeGateway
        assert settings.STOCK_HOLD_TTL_SECONDS == 600, \
            "this test is pinned to the shipped TTL; update it deliberately"
        at = datetime.fromisoformat(CashfreeGateway._expiry_iso())
        delta = (at - datetime.now(timezone.utc)).total_seconds()
        assert delta > 15 * 60, \
            f"Cashfree refuses anything inside 15 minutes; sent {delta}s"
        assert delta < 30 * 24 * 60 * 60

    def test_the_timestamp_is_offset_aware_and_in_the_future(self):
        """Cashfree rejects a naive timestamp, and microseconds."""
        from app.modules.carevo_payments.gateway import CashfreeGateway
        raw = CashfreeGateway._expiry_iso()
        at = datetime.fromisoformat(raw)
        assert at.tzinfo is not None, f"naive timestamp: {raw!r}"
        assert at.microsecond == 0, f"microseconds present: {raw!r}"
        delta = (at - datetime.now(timezone.utc)).total_seconds()
        assert 0 < delta <= CashfreeGateway.expiry_seconds() + 5

    @staticmethod
    async def _capture_create_order_body(monkeypatch) -> dict:
        """The body actually handed to httpx by a real create_order call.

        Patching the AsyncClient CLASS the gateway constructs, not
        httpx.AsyncClient.post — the latter would also hijack any in-process
        test client, which is how a test like this passes while reaching
        nothing.
        """
        from app.modules.carevo_payments import gateway as gw_mod
        from app.modules.carevo_payments.gateway import CashfreeGateway

        captured: dict = {}

        class _Resp:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {"payment_session_id": "sess_test",
                        "cf_order_id": "cf_test", "order_amount": 100.0,
                        "order_currency": "INR"}

        class _Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, json=None):
                captured.update(json or {})
                return _Resp()

        monkeypatch.setattr(gw_mod.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(gw_mod.settings, "CASHFREE_APP_ID", "test-app")
        monkeypatch.setattr(gw_mod.settings, "CASHFREE_SECRET_KEY", "test-secret")

        await CashfreeGateway().create_order(100.0, receipt=str(uuid.uuid4()))
        return captured

    @pytest.mark.asyncio
    async def test_create_order_sends_order_expiry_time(self, monkeypatch):
        """The field has to reach the wire, not just exist as a helper."""
        from app.modules.carevo_payments.gateway import CashfreeGateway

        captured = await self._capture_create_order_body(monkeypatch)

        assert "order_expiry_time" in captured, \
            f"no order_expiry_time in the create-order body: {sorted(captured)}"
        at = datetime.fromisoformat(captured["order_expiry_time"])
        assert at.tzinfo is not None
        delta = (at - datetime.now(timezone.utc)).total_seconds()
        assert 0 < delta <= CashfreeGateway.expiry_seconds() + 5

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ttl", [60, 600, 960])
    async def test_the_wire_value_clears_15_minutes_for_any_short_ttl(
            self, ttl, monkeypatch):
        """The regression, asserted where it actually failed: ON THE WIRE.

        `expiry_seconds()` being right is necessary and not sufficient — the
        400 came back because of the timestamp in the body, so that is what
        gets checked. 600 is the production TTL that was being refused.
        """
        monkeypatch.setattr(settings, "STOCK_HOLD_TTL_SECONDS", ttl)

        captured = await self._capture_create_order_body(monkeypatch)

        at = datetime.fromisoformat(captured["order_expiry_time"])
        delta = (at - datetime.now(timezone.utc)).total_seconds()
        assert delta >= 960 - 5, \
            (f"hold TTL {ttl}s produced an expiry {delta}s out; Cashfree "
             f'refuses this with "Expiry time should be more than 15 min"')
        assert delta < 30 * 24 * 60 * 60

    @pytest.mark.asyncio
    async def test_the_wire_value_equals_a_ttl_above_the_floor(self, monkeypatch):
        monkeypatch.setattr(settings, "STOCK_HOLD_TTL_SECONDS", 3600)

        captured = await self._capture_create_order_body(monkeypatch)

        at = datetime.fromisoformat(captured["order_expiry_time"])
        delta = (at - datetime.now(timezone.utc)).total_seconds()
        assert 3600 - 5 <= delta <= 3600, \
            f"a 3600s TTL should be sent as itself, not clamped; got {delta}s"

    @pytest.mark.asyncio
    async def test_the_wire_value_never_exceeds_29_days(self, monkeypatch):
        monkeypatch.setattr(settings, "STOCK_HOLD_TTL_SECONDS", 90 * 24 * 60 * 60)

        captured = await self._capture_create_order_body(monkeypatch)

        at = datetime.fromisoformat(captured["order_expiry_time"])
        delta = (at - datetime.now(timezone.utc)).total_seconds()
        assert delta <= 29 * 24 * 60 * 60


# ========================= 5. the hoarding cap ===============================

@pytest.mark.asyncio
class TestHoardingCap:
    async def test_a_second_unpaid_order_at_the_same_outlet_is_refused(
            self, client, seed, db):
        """Otherwise the TTL is a loophole: nothing stops one account ordering
        in a loop and abandoning each, holding a dish's whole stock for ten
        minutes at a time at no cost."""
        await _set_stock(db, seed["menu_item_id"], 10)
        first = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert first.status_code == 200

        second = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        assert detail["error"] == "UNPAID_ORDER_PENDING"
        assert detail["order_id"] == first.json()["id"]
        # No units taken by the refused attempt.
        assert await _stock(db, seed["menu_item_id"]) == 9

    async def test_the_message_is_for_a_human_and_names_no_uuid(
            self, client, seed, db):
        """customer_app renders detail['message'] verbatim in a SnackBar, so a
        uuid in the prose would be shown to the customer. The id travels as
        DATA alongside it for deep-linking."""
        await _set_stock(db, seed["menu_item_id"], 10)
        await _place_one(client, seed, seed["menu_item_id"], qty=1)
        detail = (await _place_one(
            client, seed, seed["menu_item_id"], qty=1)).json()["detail"]

        message = detail["message"]
        assert "unpaid order" in message.lower()
        assert detail["order_id"] not in message
        assert "uuid" not in message.lower() and "{" not in message

    async def test_paying_the_first_order_unblocks_the_next(
            self, client, seed, db):
        """Existing paid-order flows are unchanged: a customer with food on the
        way can order again immediately."""
        await _set_stock(db, seed["menu_item_id"], 10)
        first = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert (await _pay(client, seed, first.json()["id"])).status_code == 200

        second = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert second.status_code == 200, \
            f"a paid customer was blocked from ordering again: {second.text}"

    async def test_a_lapsed_hold_does_not_block_its_own_owner(
            self, client, seed, db):
        """The cap runs AFTER the sweep, so a customer whose hold expired is not
        locked out by their own abandoned order — which would be the cap
        punishing exactly the person it is not aimed at."""
        await _set_stock(db, seed["menu_item_id"], 10)
        first = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        await _force_expired(db, first.json()["id"])

        second = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert second.status_code == 200, \
            f"a customer was blocked by their own lapsed hold: {second.text}"

    async def test_another_customer_is_unaffected(self, client, seed, db):
        """Per CUSTOMER, not per outlet. A busy restaurant is the normal case."""
        await _set_stock(db, seed["menu_item_id"], 10)
        assert (await _place_one(
            client, seed, seed["menu_item_id"], qty=1)).status_code == 200

        other = (await _customers(db, 1))[0]
        theirs = await _place_one(client, seed, seed["menu_item_id"], qty=1,
                                  auth=other)
        assert theirs.status_code == 200, \
            f"one customer's hold blocked another's order: {theirs.text}"

    async def test_an_untracked_item_is_not_capped(self, client, seed, db):
        """No stock number means no reservation row, so there is nothing to
        hoard and the cap must not fire. This is every item at every outlet
        until a restaurant opts in, so a false positive here would break
        ordering everywhere."""
        await _set_stock(db, seed["menu_item_id"], None)
        for _ in range(3):
            r = await _place_one(client, seed, seed["menu_item_id"], qty=1)
            assert r.status_code == 200, \
                f"the cap fired on an untracked item: {r.text}"
        assert await _reservations(db, r.json()["id"]) == []
