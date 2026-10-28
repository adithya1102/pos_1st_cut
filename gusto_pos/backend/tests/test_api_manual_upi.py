"""Direct UPI — payment_mode 'UPI_MANUAL' (migration 035).

The customer pays the restaurant's own VPA from their own UPI app, taps "I've
paid", and the restaurant checks its UPI app before accepting. CareVo is never
in the payment path, which is what makes every refund rule here different from
the gateway ones.

THE FIVE ASSERTIONS THAT MATTER MOST
------------------------------------
1. `TestAcceptRecordsPaymentOnce` — the Accept tap IS the payment
   confirmation, and a double-tap must not record the money twice.

2. `TestRejectOutcomes` — 'not_received' and 'cannot_make' look identical in
   `status` and are opposites: one strikes the customer and owes nothing, the
   other owes the customer their money back.

3. `TestNeverInTheCashfreeQueue` — a direct-UPI refund must never appear in
   /admin/orders/refund-due. CareVo cannot reverse a payment it never touched,
   and listing it as though it could is how a customer gets told a refund is
   coming that nobody is able to send.

4. `TestPayWindow` — the window must stay inside the stock hold, or the units
   are reclaimed while the customer is still in their UPI app.

5. `TestUnpaidUpiOrderCannotBeHandedOver` — the money guard, extended from
   pay-at-pickup: an unaccepted UPI order cannot be verified through.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.security import get_password_hash
from app.modules.carevo_customer.acceptance import (
    AWAITING, EXPIRED, AcceptanceService,
)
from app.modules.carevo_customer.service import (
    FALSE_CLAIM_STRIKE_LIMIT, PAY_AT_PICKUP, PAY_PREPAID, PAY_UPI_MANUAL,
    UPI_PAY_WINDOW_SECONDS, CarevoService,
)
from tests.conftest import API

VPA = "testrestaurant@okaxis"
PAYEE = "Test Kitchen"


# ------------------------------- helpers -------------------------------------

async def _enable_upi(db, outlet_id, *, prepaid=False, pickup=False) -> None:
    """Turn direct UPI on directly, with the attestation the CHECK requires."""
    await db.execute(text("""
        UPDATE outlets SET payment_prepaid_enabled = :p,
                           payment_pay_at_pickup_enabled = :k,
                           payment_upi_manual_enabled = true,
                           upi_vpa = :v, upi_payee_name = :n,
                           upi_attested_at = now(),
                           is_manually_closed = false
         WHERE id = :oid
    """), {"p": prepaid, "k": pickup, "v": VPA, "n": PAYEE,
           "oid": str(outlet_id)})
    await db.commit()


async def _order_row(db, order_id):
    return (await db.execute(text("""
        SELECT status, payment_status, payment_mode, acceptance_state,
               payment_claimed_at, manual_refund_due, manual_refund_reason,
               refund_required, refund_reason, pickup_code, collected_payment_method,
               total_amount, customer_id
          FROM customer_orders WHERE id = :i
    """), {"i": str(order_id)})).first()


async def _txns(db, order_id) -> list[tuple]:
    rows = (await db.execute(text("""
        SELECT gateway, method, status, amount FROM payment_transactions
         WHERE customer_order_id = :i ORDER BY created_at
    """), {"i": str(order_id)})).fetchall()
    return [(r.gateway, r.method, r.status, float(r.amount or 0)) for r in rows]


async def _events(db, order_id) -> list[str]:
    rows = (await db.execute(text(
        "SELECT event_type FROM order_events WHERE order_id = :i ORDER BY seq"),
        {"i": str(order_id)})).fetchall()
    return [r.event_type for r in rows]


async def _stock_states(db, order_id) -> list[str]:
    rows = (await db.execute(text(
        "SELECT state FROM stock_reservations WHERE order_id = :i"),
        {"i": str(order_id)})).fetchall()
    return [r.state for r in rows]


async def _place(client, seed, *, method=PAY_UPI_MANUAL, qty=2, extra=None):
    body = {
        "outlet_id": seed["outlet_id"],
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": qty}],
    }
    if method is not None:
        body["payment_method"] = method
    if extra:
        body.update(extra)
    return await client.post(f"{API}/customer/orders",
                             headers=seed["customer_auth"], json=body)


async def _place_ok(client, seed, **kw) -> dict:
    r = await _place(client, seed, **kw)
    assert r.status_code == 200, r.text
    return r.json()


async def _claim(client, seed, order_id):
    return await client.post(f"{API}/customer/orders/{order_id}/claim-paid",
                             headers=seed["customer_auth"])


async def _accept(client, seed, order_id, *, prep=15):
    return await client.post(f"{API}/pos/orders/{order_id}/accept",
                             headers=seed["owner_auth"],
                             json={"prep_minutes": prep})


async def _advance(client, seed, order_id, status):
    return await client.post(f"{API}/customer/orders/{order_id}/advance",
                             headers=seed["owner_auth"],
                             json={"status": status})


async def _second_outlet(db, seed):
    tag = uuid.uuid4().hex[:8]
    oid, uid = uuid.uuid4(), uuid.uuid4()
    org = await db.scalar(text(
        "SELECT organization_id FROM outlets WHERE id = :o"),
        {"o": seed["outlet_id"]})
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city,
                             is_visible, upi_id, geofence_radius_meters,
                             verification_status, created_at)
        VALUES (:i,:o,:n,'T', true, 'x@upi', 150, 'active', now())"""),
        {"i": str(oid), "o": str(org), "n": f"Other {tag}"})
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i,:u,:h, true, :o, now())"""),
        {"i": str(uid), "u": f"other_{tag}",
         "h": get_password_hash("correct-horse"), "o": str(oid)})
    await db.commit()
    return {"outlet_id": str(oid),
            "auth": {"Authorization":
                     f"Bearer {create_access_token(subject=f'other_{tag}')}"}}


# ========================= 1. the resolver table =============================

class TestResolverWithThreeFlags:
    @pytest.mark.parametrize(
        "prepaid,pickup,upi,unlocked,expected", [
            (True,  False, False, True,  [PAY_PREPAID]),
            (False, True,  False, True,  [PAY_AT_PICKUP]),
            (False, False, True,  True,  [PAY_UPI_MANUAL]),
            (True,  True,  True,  True,  [PAY_PREPAID, PAY_AT_PICKUP, PAY_UPI_MANUAL]),
            (True,  False, True,  True,  [PAY_PREPAID, PAY_UPI_MANUAL]),
            # The platform lock withdraws prepaid whatever the owner flag says.
            (True,  False, True,  False, [PAY_UPI_MANUAL]),
            (True,  True,  False, False, [PAY_AT_PICKUP]),
        ])
    async def test_the_whole_table(self, db, seed, prepaid, pickup, upi,
                                   unlocked, expected):
        await db.execute(text("""
            UPDATE outlets SET payment_prepaid_enabled = :p,
                               payment_pay_at_pickup_enabled = :k,
                               payment_upi_manual_enabled = :u,
                               cashfree_unlocked = :c,
                               upi_vpa = :v, upi_payee_name = :n,
                               upi_attested_at = now()
             WHERE id = :oid
        """), {"p": prepaid, "k": pickup, "u": upi, "c": unlocked,
               "v": VPA, "n": PAYEE, "oid": seed["outlet_id"]})
        await db.commit()
        assert await CarevoService.payment_methods_for(
            db, seed["outlet_id"]) == expected

    async def test_upi_withdrawn_without_a_verified_phone(self, db, seed):
        from app.modules.carevo_customer.deps import create_customer_token
        cid = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO customers (id, name, google_uid, points_balance,
                                   created_at)
            VALUES (:i, 'Googler', :g, 0, now())"""),
            {"i": str(cid), "g": f"guid-{uuid.uuid4().hex[:12]}"})
        await db.commit()
        await _enable_upi(db, seed["outlet_id"], prepaid=True)

        cust = (await db.execute(text(
            "SELECT * FROM customers WHERE id = :i"), {"i": str(cid)})).first()
        methods = await CarevoService.payment_methods_for(
            db, seed["outlet_id"], cust)
        assert methods == [PAY_PREPAID], "no phone, no direct UPI"

    async def test_upi_withdrawn_after_two_false_claims(self, db, seed):
        """false_claim_count, NOT no_show_count: a UPI order is paid before the
        kitchen starts, so there is no food to waste by not turning up."""
        await _enable_upi(db, seed["outlet_id"], prepaid=True)
        await db.execute(text(
            "UPDATE customers SET false_claim_count = :n WHERE id = :i"),
            {"n": FALSE_CLAIM_STRIKE_LIMIT, "i": seed["customer_id"]})
        await db.commit()
        cust = (await db.execute(text(
            "SELECT * FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})).first()
        assert await CarevoService.payment_methods_for(
            db, seed["outlet_id"], cust) == [PAY_PREPAID]

    async def test_no_show_strikes_do_not_block_upi(self, db, seed):
        """And the converse: the two counters are independent."""
        await _enable_upi(db, seed["outlet_id"])
        await db.execute(text(
            "UPDATE customers SET no_show_count = 5 WHERE id = :i"),
            {"i": seed["customer_id"]})
        await db.commit()
        cust = (await db.execute(text(
            "SELECT * FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})).first()
        assert PAY_UPI_MANUAL in await CarevoService.payment_methods_for(
            db, seed["outlet_id"], cust)

    async def test_it_is_on_the_menu_and_outlet_payloads(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"], prepaid=True)

        m = await client.get(f"{API}/customer/menu/{seed['outlet_id']}",
                             headers=seed["customer_auth"])
        assert m.status_code == 200, m.text
        assert m.json()["payment_methods"] == [PAY_PREPAID, PAY_UPI_MANUAL]

        o = await client.get(f"{API}/customer/outlets",
                             headers=seed["customer_auth"])
        mine = [x for x in o.json() if x["id"] == seed["outlet_id"]]
        assert mine and PAY_UPI_MANUAL in mine[0]["payment_methods"]

    async def test_an_unavailable_method_is_refused_before_any_write(
            self, client, db, seed):
        await db.execute(text(
            "UPDATE outlets SET payment_prepaid_enabled = true, "
            "       payment_upi_manual_enabled = false WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        before = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id = :o"),
            {"o": seed["outlet_id"]})

        r = await _place(client, seed, method=PAY_UPI_MANUAL)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

        after = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id = :o"),
            {"o": seed["outlet_id"]})
        assert after == before, "a refused order must leave NO row"


# ============================== 2. placement =================================

class TestPlacement:
    async def test_order_shape_and_upi_block(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)

        assert order["payment"] is None, "no gateway session"
        assert order["payment_mode"] == PAY_UPI_MANUAL
        block = order["upi_payment"]
        assert block["vpa"] == VPA
        assert block["payee_name"] == PAYEE
        assert block["amount"] == 200.0
        assert block["note"] == CarevoService.short_order_number(order["id"])
        # The note is NOT the pickup code — that must never travel through a
        # payment app or land on a bank statement.
        assert (await _order_row(db, order["id"])).pickup_code is None

        row = await _order_row(db, order["id"])
        assert row.status == "CREATED"
        assert row.payment_status == "PENDING"
        assert row.payment_mode == PAY_UPI_MANUAL
        # NOT awaiting yet — the clock opens at the claim, because there is
        # nothing for the restaurant to decide until the customer has paid.
        assert row.acceptance_state is None
        assert row.payment_claimed_at is None
        assert await _txns(db, order["id"]) == []

    async def test_the_contact_is_snapshotted(self, client, db, seed):
        """The restaurant must be able to reach whoever claimed to have paid."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        cust = (await db.execute(text(
            "SELECT name, phone_number FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})).first()
        snap = (await db.execute(text(
            "SELECT contact_name, contact_phone, call_state "
            "FROM customer_orders WHERE id = :i"), {"i": order["id"]})).first()
        assert snap.contact_name == cust.name
        assert snap.contact_phone == cust.phone_number
        # call_state stays NULL — nobody rings a direct-UPI customer as part of
        # the flow, so "is there a call to make" stays answerable from it.
        assert snap.call_state is None

    async def test_stock_is_held_not_committed(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        order = await _place_ok(client, seed)
        assert await _stock_states(db, order["id"]) == ["HELD"]

    async def test_no_gateway_call_is_made(self, client, db, seed, monkeypatch):
        from app.modules.carevo_payments import gateway as gw_mod
        called = []

        async def _boom(*a, **k):
            called.append(1)
            raise AssertionError("the gateway must not be called")

        monkeypatch.setattr(gw_mod.StubRazorpayGateway, "create_order", _boom)
        await _enable_upi(db, seed["outlet_id"])
        await _place_ok(client, seed)
        assert called == []

    async def test_scheduling_is_refused(self, client, db, seed):
        from datetime import datetime, timedelta, timezone
        await _enable_upi(db, seed["outlet_id"])
        before = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id = :o"),
            {"o": seed["outlet_id"]})
        when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

        r = await _place(client, seed, extra={"requested_pickup_at": when})
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "SCHEDULING_UNAVAILABLE_FOR_PICKUP_PAYMENT"
        assert "UPI" in detail["message"]

        after = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id = :o"),
            {"o": seed["outlet_id"]})
        assert after == before

    async def test_the_open_order_cap_is_shared_with_pay_at_pickup(
            self, client, db, seed):
        """One open unpaid order, whichever way it was going to be paid."""
        await _enable_upi(db, seed["outlet_id"], pickup=True)
        first = await _place_ok(client, seed, method=PAY_UPI_MANUAL)

        r = await _place(client, seed, method=PAY_AT_PICKUP)
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "OPEN_PICKUP_ORDER_PENDING"
        assert detail["order_id"] == first["id"]

    async def test_the_order_is_not_on_the_owner_queue_until_claimed(
            self, client, db, seed):
        """Nothing for the restaurant to do until the customer says they paid."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)

        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert order["id"] not in [o["order_id"] for o in r.json()]


# ================================ 3. the claim ===============================

class TestClaim:
    @pytest.fixture
    async def placed(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        return await _place_ok(client, seed)

    async def test_claim_commits_stock_and_opens_the_window(
            self, client, db, seed, placed):
        r = await _claim(client, seed, placed["id"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["claimed"] is True
        assert body["already"] is False
        assert body["payment_claimed_at"] is not None

        row = await _order_row(db, placed["id"])
        assert row.payment_claimed_at is not None
        # STILL NOT PAID. A claim is an assertion by one party.
        assert row.payment_status == "PENDING"
        assert row.status == "CREATED"
        assert row.acceptance_state == AWAITING
        assert await _stock_states(db, placed["id"]) == ["COMMITTED"]
        assert "PAYMENT_CLAIMED" in await _events(db, placed["id"])

    async def test_claim_is_idempotent(self, client, db, seed, placed):
        first = await _claim(client, seed, placed["id"])
        assert first.json()["already"] is False
        at = first.json()["payment_claimed_at"]

        second = await _claim(client, seed, placed["id"])
        assert second.status_code == 200, second.text
        assert second.json()["already"] is True
        assert second.json()["payment_claimed_at"] == at, "the clock not reset"
        # And exactly one claim event.
        assert (await _events(db, placed["id"])).count("PAYMENT_CLAIMED") == 1

    async def test_concurrent_claims_resolve_to_one(self, client, db, seed, placed):
        r1, r2 = await asyncio.gather(
            _claim(client, seed, placed["id"]),
            _claim(client, seed, placed["id"]),
            return_exceptions=True)
        codes = [getattr(r, "status_code", 500) for r in (r1, r2)
                 if not isinstance(r, Exception)]
        assert 200 in codes
        assert (await _events(db, placed["id"])).count("PAYMENT_CLAIMED") == 1

    async def test_only_the_orders_own_customer_can_claim(
            self, client, db, seed, placed):
        from app.modules.carevo_customer.deps import create_customer_token
        cid = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO customers (id, phone_number, name, points_balance,
                                   created_at)
            VALUES (:i, :p, 'Someone Else', 0, now())"""),
            {"i": str(cid), "p": f"+9188{uuid.uuid4().hex[:8]}"})
        await db.commit()
        other = {"Authorization": f"Bearer {create_customer_token(str(cid))}"}

        r = await client.post(
            f"{API}/customer/orders/{placed['id']}/claim-paid", headers=other)
        # 403, not 404: claim_upi_payment reuses CarevoService.get_order rather
        # than re-implementing ownership, and that is the code it has always
        # returned for somebody else's order (service.py:2139-2140). Asserted
        # as it is rather than changed — altering a shared refusal to suit a
        # new endpoint would move behaviour under every existing caller.
        assert r.status_code == 403, r.text
        assert (await _order_row(db, placed["id"])).payment_claimed_at is None

    async def test_a_prepaid_order_cannot_be_claimed(self, client, db, seed):
        await db.execute(text(
            "UPDATE outlets SET payment_prepaid_enabled = true WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        order = await _place_ok(client, seed, method=PAY_PREPAID)
        r = await _claim(client, seed, order["id"])
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "NOT_A_UPI_ORDER"

    async def test_the_order_reaches_the_owner_queue_after_the_claim(
            self, client, db, seed, placed):
        await _claim(client, seed, placed["id"])
        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        row = next((o for o in r.json() if o["order_id"] == placed["id"]), None)
        assert row is not None, "now there is something to decide"
        assert row["payment_mode"] == PAY_UPI_MANUAL
        assert row["payment_claimed_at"] is not None
        assert row["payment_status"] == "PENDING"
        assert row["contact_phone"], "so the restaurant can chase it"


class TestPayWindow:
    def test_the_window_stays_inside_the_stock_hold(self):
        """A window longer than the hold hands the units back while the
        customer is still in their UPI app."""
        assert UPI_PAY_WINDOW_SECONDS < settings.STOCK_HOLD_TTL_SECONDS, (
            f"UPI_PAY_WINDOW_SECONDS ({UPI_PAY_WINDOW_SECONDS}s) must stay "
            f"below STOCK_HOLD_TTL_SECONDS "
            f"({settings.STOCK_HOLD_TTL_SECONDS}s)")

    async def test_a_claim_past_the_window_is_refused(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await db.execute(text(
            "UPDATE customer_orders SET created_at = now() - "
            "make_interval(secs => :w) - interval '1 minute' WHERE id = :i"),
            {"w": UPI_PAY_WINDOW_SECONDS, "i": order["id"]})
        await db.commit()

        r = await _claim(client, seed, order["id"])
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PAY_WINDOW_EXPIRED"

    async def test_unclaimed_orders_are_swept_with_no_refund(
            self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        order = await _place_ok(client, seed)
        await db.execute(text(
            "UPDATE customer_orders SET created_at = now() - "
            "make_interval(secs => :w) - interval '1 minute' WHERE id = :i"),
            {"w": UPI_PAY_WINDOW_SECONDS, "i": order["id"]})
        await db.commit()

        n = await CarevoService.expire_unclaimed_upi_orders(
            db, outlet_id=seed["outlet_id"])
        assert n == 1

        row = await _order_row(db, order["id"])
        assert row.status == "CANCELLED"
        # NOBODY EVER SAID MONEY WAS SENT, so nothing is owed on either axis.
        assert row.refund_required is False
        assert row.manual_refund_due is False
        assert await _stock_states(db, order["id"]) == ["RELEASED"]
        # And the cap is clear again — asserted on the STATUS, not on the
        # response object being non-None, which it always is.
        again = await _place(client, seed)
        assert again.status_code == 200, again.text

    async def test_a_claimed_order_is_not_swept_by_the_pay_window(
            self, client, db, seed):
        """It expires through the acceptance deadline instead, which DOES flag
        a manual refund."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])
        await db.execute(text(
            "UPDATE customer_orders SET created_at = now() - "
            "make_interval(secs => :w) - interval '1 minute' WHERE id = :i"),
            {"w": UPI_PAY_WINDOW_SECONDS, "i": order["id"]})
        await db.commit()

        assert await CarevoService.expire_unclaimed_upi_orders(
            db, outlet_id=seed["outlet_id"]) == 0
        assert (await _order_row(db, order["id"])).status == "CREATED"

    async def test_the_sweep_runs_from_the_owner_queue_poll(
            self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await db.execute(text(
            "UPDATE customer_orders SET created_at = now() - "
            "make_interval(secs => :w) - interval '1 minute' WHERE id = :i"),
            {"w": UPI_PAY_WINDOW_SECONDS, "i": order["id"]})
        await db.commit()

        await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        assert (await _order_row(db, order["id"])).status == "CANCELLED"


# ============================ 4. accept = payment ============================

class TestAcceptRecordsPaymentOnce:
    @pytest.fixture
    async def claimed(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])
        return order

    async def test_accept_records_the_payment_and_mints_the_code(
            self, client, db, seed, claimed):
        r = await _accept(client, seed, claimed["id"], prep=20)
        assert r.status_code == 200, r.text
        assert r.json()["acceptance_state"] == "ACCEPTED"
        assert r.json()["status"] == "RECEIVED"

        row = await _order_row(db, claimed["id"])
        assert row.payment_status == "PAID", "the Accept tap IS the confirmation"
        assert row.collected_payment_method == "upi"
        assert row.status == "RECEIVED"
        assert row.pickup_code and len(row.pickup_code) == 6

        # One transaction, named for the path it came through.
        assert await _txns(db, claimed["id"]) == [
            ("upi_manual", "upi", "PAID", 200.0)]

        kinds = await _events(db, claimed["id"])
        assert "ORDER_PAID" in kinds, "every existing reader keeps working"
        assert "PAYMENT_COLLECTED" in kinds
        assert "ORDER_ACCEPTED" in kinds

        pts = await db.scalar(text(
            "SELECT points_balance FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})
        assert float(pts) > 0, "loyalty accrues like any other payment"

    async def test_a_double_tap_records_the_money_exactly_once(
            self, client, db, seed, claimed):
        first = await _accept(client, seed, claimed["id"])
        assert first.status_code == 200, first.text
        second = await _accept(client, seed, claimed["id"])
        assert second.status_code == 409, second.text

        assert len(await _txns(db, claimed["id"])) == 1
        assert (await _events(db, claimed["id"])).count("ORDER_PAID") == 1

    async def test_two_tablets_at_once_record_the_money_exactly_once(
            self, client, db, seed, claimed):
        r1, r2 = await asyncio.gather(
            _accept(client, seed, claimed["id"]),
            _accept(client, seed, claimed["id"]),
            return_exceptions=True)
        codes = sorted(getattr(r, "status_code", 500) for r in (r1, r2)
                       if not isinstance(r, Exception))
        assert 200 in codes
        assert len(await _txns(db, claimed["id"])) == 1

    async def test_accept_is_refused_before_a_claim(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        # Force AWAITING without a claim, which should not be reachable.
        await db.execute(text(
            "UPDATE customer_orders SET acceptance_state = 'AWAITING' "
            " WHERE id = :i"), {"i": order["id"]})
        await db.commit()

        r = await _accept(client, seed, order["id"])
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_NOT_CLAIMED"
        assert (await _order_row(db, order["id"])).payment_status == "PENDING"

    async def test_a_paid_upi_order_completes_through_verify_pickup(
            self, client, db, seed, claimed):
        """The ORDINARY handover path, exactly like a prepaid order."""
        await _accept(client, seed, claimed["id"])
        await _advance(client, seed, claimed["id"], "READY")
        code = (await _order_row(db, claimed["id"])).pickup_code

        v = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=seed["owner_auth"],
                              json={"order_id": claimed["id"],
                                    "pickup_code": code})
        assert v.status_code == 200, v.text
        assert v.json()["verified"] is True
        assert (await _order_row(db, claimed["id"])).status == "COMPLETED"


class TestUnpaidUpiOrderCannotBeHandedOver:
    async def test_advance_without_accept_is_refused(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])

        r = await _advance(client, seed, order["id"], "RECEIVED")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "NOT_ACCEPTED"
        row = await _order_row(db, order["id"])
        assert row.status == "CREATED"
        assert row.pickup_code is None

    async def test_verify_pickup_on_an_unpaid_upi_order_is_refused(
            self, client, db, seed):
        """The money guard, extended from pay-at-pickup."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])
        # Force a live status and a code without going through accept.
        await db.execute(text(
            "UPDATE customer_orders SET status = 'READY', "
            "       pickup_code = '234567' WHERE id = :i"), {"i": order["id"]})
        await db.commit()

        r = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=seed["owner_auth"],
                              json={"order_id": order["id"],
                                    "pickup_code": "234567"})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_NOT_RECORDED"
        assert (await _order_row(db, order["id"])).status == "READY"

    async def test_mark_paid_is_inert_for_a_upi_order(self, client, db, seed):
        """A signed webhook naming it, or /payment/simulate, must do nothing."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)

        r = await client.post(f"{API}/customer/payment/simulate",
                              headers=seed["customer_auth"],
                              json={"order_id": order["id"], "method": "upi"})
        assert r.status_code == 200, r.text
        row = await _order_row(db, order["id"])
        assert row.payment_status == "PENDING", "a customer cannot self-pay"
        assert row.pickup_code is None


# ========================= 5. reject: the two outcomes =======================

class TestRejectOutcomes:
    @pytest.fixture
    async def claimed(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])
        return order

    async def test_not_received_strikes_the_customer_and_owes_nothing(
            self, client, db, seed, claimed):
        r = await client.post(f"{API}/pos/orders/{claimed['id']}/reject",
                              headers=seed["owner_auth"],
                              json={"reason": "No payment in my UPI app",
                                    "upi_outcome": "not_received"})
        assert r.status_code == 200, r.text

        row = await _order_row(db, claimed["id"])
        assert row.status == "CANCELLED"
        assert row.manual_refund_due is False, "no money was ever sent"
        assert row.refund_required is False, "and never the gateway queue"

        strikes = await db.scalar(text(
            "SELECT false_claim_count FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})
        assert strikes == 1
        assert "PAYMENT_NOT_RECEIVED" in await _events(db, claimed["id"])

    async def test_cannot_make_owes_the_money_back(
            self, client, db, seed, claimed):
        r = await client.post(f"{API}/pos/orders/{claimed['id']}/reject",
                              headers=seed["owner_auth"],
                              json={"reason": "Kitchen closed early",
                                    "upi_outcome": "cannot_make"})
        assert r.status_code == 200, r.text

        row = await _order_row(db, claimed["id"])
        assert row.status == "CANCELLED"
        assert row.manual_refund_due is True
        assert row.manual_refund_reason == "Kitchen closed early"
        assert row.refund_required is False, "NEVER the gateway queue"

        strikes = await db.scalar(text(
            "SELECT false_claim_count FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})
        assert strikes == 0, "the customer did nothing wrong"
        assert "MANUAL_REFUND_DUE" in await _events(db, claimed["id"])

    async def test_an_unclaimed_reject_is_an_ordinary_refusal(
            self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)

        r = await client.post(f"{API}/pos/orders/{order['id']}/reject",
                              headers=seed["owner_auth"],
                              json={"upi_outcome": "not_received"})
        assert r.status_code == 200, r.text
        row = await _order_row(db, order["id"])
        assert row.status == "CANCELLED"
        # No claim means no assertion to have been false and nothing to refund.
        assert row.manual_refund_due is False
        assert await db.scalar(text(
            "SELECT false_claim_count FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]}) == 0

    async def test_expiry_after_a_claim_owes_the_money_back(
            self, client, db, seed, claimed):
        """Nobody looked, and by now the money may really be there."""
        await db.execute(text(
            "UPDATE customer_orders SET acceptance_deadline_at = "
            "now() - interval '1 minute' WHERE id = :i"), {"i": claimed["id"]})
        await db.commit()

        res = await AcceptanceService.process_acceptance_deadlines(
            db, order_id=claimed["id"])
        assert res["expired"] == 1

        row = await _order_row(db, claimed["id"])
        assert row.acceptance_state == EXPIRED
        assert row.status == "CANCELLED"
        assert row.manual_refund_due is True
        assert row.manual_refund_reason == (
            "acceptance_expired_after_payment_claim")
        assert row.refund_required is False, "NEVER the gateway queue"
        assert "MANUAL_REFUND_DUE" in await _events(db, claimed["id"])


class TestNeverInTheCashfreeQueue:
    async def test_manual_refunds_are_absent_from_the_admin_refund_list(
            self, client, db, seed):
        """CareVo cannot reverse a payment it was never in the path of, so
        listing one as refundable would promise something nobody can send."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])
        await client.post(f"{API}/pos/orders/{order['id']}/reject",
                          headers=seed["owner_auth"],
                          json={"upi_outcome": "cannot_make"})

        assert (await _order_row(db, order["id"])).manual_refund_due is True

        r = await client.get(f"{API}/admin/orders/refund-due",
                             headers=seed["admin_auth"])
        assert r.status_code == 200, r.text
        ids = [str(x.get("order_id")) for x in r.json()]
        assert order["id"] not in ids, "the gateway queue must not list it"

    async def test_a_gateway_refund_still_reaches_that_queue(
            self, client, db, seed, paid_order):
        """The prepaid path is untouched: a rejected PAID order still appears."""
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/reject",
                              headers=seed["owner_auth"], json={})
        assert r.status_code == 200, r.text
        q = await client.get(f"{API}/admin/orders/refund-due",
                             headers=seed["admin_auth"])
        ids = [str(x.get("order_id")) for x in q.json()]
        assert paid_order["id"] in ids


# ========================= 6. contact + cross-outlet =========================

class TestContactScoping:
    async def test_only_the_receiving_outlet_sees_the_contact(
            self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])
        other = await _second_outlet(db, seed)

        mine = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        row = next(o for o in mine.json() if o["order_id"] == order["id"])
        assert row["contact_phone"]
        assert row["contact_visible"] is True

        theirs = await client.get(f"{API}/pos/orders", headers=other["auth"])
        assert order["id"] not in [o["order_id"] for o in theirs.json()]
        phone = row["contact_phone"]
        assert phone not in theirs.text

    async def test_the_customer_response_carries_no_contact(
            self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)

        r = await client.get(f"{API}/customer/orders/{order['id']}",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert "contact_phone" not in body
        assert "contact_name" not in body
        # But the pay block IS there, so the screen survives a restart.
        assert body["upi_payment"]["vpa"] == VPA
        assert body["payment_mode"] == PAY_UPI_MANUAL

    async def test_the_pay_block_disappears_once_paid(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])
        await _accept(client, seed, order["id"])

        r = await client.get(f"{API}/customer/orders/{order['id']}",
                             headers=seed["customer_auth"])
        assert r.json()["upi_payment"] is None, "nothing left to pay"

    async def test_cross_outlet_accept_is_a_404(self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place_ok(client, seed)
        await _claim(client, seed, order["id"])
        other = await _second_outlet(db, seed)
        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              headers=other["auth"], json={"prep_minutes": 15})
        assert r.status_code == 404


# ======================= 7. regressions (CRITICAL) ===========================

class TestPrepaidRegression:
    async def test_the_whole_prepaid_flow_is_unchanged(self, client, db, seed):
        order = await _place_ok(client, seed, method=None)
        assert order["payment"] is not None
        assert order["payment"]["gateway"] == "razorpay"
        assert order["payment_mode"] == "PREPAID"
        assert order.get("upi_payment") is None

        row = await _order_row(db, order["id"])
        assert row.payment_mode == "PREPAID"
        assert row.payment_claimed_at is None
        assert row.manual_refund_due is False

        p = await client.post(f"{API}/customer/payment/simulate",
                              headers=seed["customer_auth"],
                              json={"order_id": order["id"], "method": "upi"})
        assert p.status_code == 200, p.text
        row = await _order_row(db, order["id"])
        assert row.payment_status == "PAID"
        assert row.pickup_code

        await _advance(client, seed, order["id"], "RECEIVED")
        await _advance(client, seed, order["id"], "READY")
        v = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=seed["owner_auth"],
                              json={"order_id": order["id"],
                                    "pickup_code": row.pickup_code})
        assert v.status_code == 200, v.text
        assert (await _order_row(db, order["id"])).status == "COMPLETED"


class TestPayAtPickupRegression:
    async def test_the_pay_at_pickup_flow_is_unchanged(self, client, db, seed):
        await db.execute(text("""
            UPDATE outlets SET payment_prepaid_enabled = false,
                               payment_pay_at_pickup_enabled = true,
                               payment_upi_manual_enabled = false
             WHERE id = :o"""), {"o": seed["outlet_id"]})
        await db.commit()

        order = await _place_ok(client, seed, method=PAY_AT_PICKUP)
        assert order["payment_mode"] == PAY_AT_PICKUP
        assert order.get("upi_payment") is None
        assert order["amount_due_at_pickup"] == 200.0

        row = await _order_row(db, order["id"])
        assert row.acceptance_state == AWAITING, "clock opens at placement"
        assert row.payment_claimed_at is None, "no claim in this flow"

        await _accept(client, seed, order["id"])
        await _advance(client, seed, order["id"], "READY")
        code = (await _order_row(db, order["id"])).pickup_code

        c = await client.post(f"{API}/pos/orders/{order['id']}/collect",
                              headers=seed["owner_auth"],
                              json={"pickup_code": code, "method": "cash"})
        assert c.status_code == 200, c.text
        row = await _order_row(db, order["id"])
        assert row.status == "COMPLETED"
        assert row.payment_status == "PAID"
        assert row.collected_payment_method == "cash"
        assert await _txns(db, order["id"]) == [("counter", "cash", "PAID", 200.0)]
