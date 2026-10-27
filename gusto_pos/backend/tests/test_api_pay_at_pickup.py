"""Pay at pickup (migration 034).

The customer orders, the restaurant RINGS THEM to confirm, and money changes
hands at the counter. Cashfree is untouched and stays in the code.

THE FIVE ASSERTIONS THAT MATTER MOST
------------------------------------
1. `TestOldBuildIsRefused` — an already-installed customer_app build sends no
   `payment_method`, which implicitly asks for prepaid. At a pay-at-pickup-only
   outlet it must be refused AND MUST LEAVE NO ROW. If this ever passes with a
   row created, the old app has a dead order holding stock on a screen that
   cannot pay for it.

2. `TestVerifyPickupMoneyGuard` — verify_pickup has never read payment_status,
   so without the 409 it would complete an unpaid pay-at-pickup order. This is
   the free-food regression test.

3. `TestExpiryFlagsNoRefund` — _expire_one used to set refund_required
   unconditionally. A pay-at-pickup order took no money, so flagging one would
   put unpayable refunds into the admin queue.

4. `TestCallWindowFitsStockHold` — call_window_s MUST stay below
   STOCK_HOLD_TTL_SECONDS or the stock hold lapses while the customer is still
   waiting for the phone to ring.

5. `TestPrepaidRegression` — the per-brief guarantee that a prepaid order is
   byte-for-byte unaffected. It walks the whole existing flow and pins
   payment_mode='PREPAID' plus the absence of every 034 field.
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
    CONTACT_REDACTION_AFTER, NO_SHOW_STRIKE_LIMIT, PAY_AT_PICKUP, PAY_PREPAID,
    CarevoService,
)
from tests.conftest import API


# ------------------------------- helpers -------------------------------------

async def _set_methods(db, outlet_id, *, prepaid: bool, pickup: bool,
                       call_window_s: int = 300) -> None:
    """Flip one outlet's payment flags directly, as the admin route would."""
    await db.execute(text("""
        UPDATE outlets SET payment_prepaid_enabled = :p,
                           payment_pay_at_pickup_enabled = :k,
                           call_window_s = :w,
                           is_manually_closed = false
         WHERE id = :oid
    """), {"p": prepaid, "k": pickup, "w": call_window_s, "oid": str(outlet_id)})
    await db.commit()


async def _order_row(db, order_id):
    return (await db.execute(text("""
        SELECT status, payment_status, payment_mode, acceptance_state,
               acceptance_deadline_at, call_state, call_attempts, first_call_at,
               contact_name, contact_phone, contact_redacted_at,
               collected_payment_method, collected_at, collected_by,
               no_show_at, refund_required, refund_reason, pickup_code,
               failed_attempts, is_locked, total_amount
          FROM customer_orders WHERE id = :i
    """), {"i": str(order_id)})).first()


async def _events(db, order_id) -> list[tuple]:
    rows = (await db.execute(text("""
        SELECT event_type, actor_type, source FROM order_events
         WHERE order_id = :i ORDER BY seq
    """), {"i": str(order_id)})).fetchall()
    return [(r.event_type, r.actor_type, r.source) for r in rows]


async def _txns(db, order_id) -> list[tuple]:
    rows = (await db.execute(text("""
        SELECT gateway, method, status, amount FROM payment_transactions
         WHERE customer_order_id = :i ORDER BY created_at
    """), {"i": str(order_id)})).fetchall()
    return [(r.gateway, r.method, r.status, float(r.amount or 0)) for r in rows]


async def _stock_states(db, order_id) -> list[str]:
    rows = (await db.execute(text("""
        SELECT state FROM stock_reservations WHERE order_id = :i
    """), {"i": str(order_id)})).fetchall()
    return [r.state for r in rows]


async def _place(client, seed, *, method=PAY_AT_PICKUP, qty=2, outlet_id=None,
                 item_id=None):
    """Place one order, returning the raw response."""
    body = {
        "outlet_id": outlet_id or seed["outlet_id"],
        "items": [{"menu_item_id": item_id or seed["menu_item_id"],
                   "quantity": qty}],
    }
    if method is not None:
        body["payment_method"] = method
    return await client.post(f"{API}/customer/orders",
                             headers=seed["customer_auth"], json=body)


async def _place_ok(client, seed, **kw) -> dict:
    r = await _place(client, seed, **kw)
    assert r.status_code == 200, r.text
    return r.json()


async def _accept(client, seed, order_id, *, prep=15):
    return await client.post(
        f"{API}/pos/orders/{order_id}/accept",
        headers=seed["owner_auth"], json={"prep_minutes": prep})


async def _advance(client, seed, order_id, status):
    return await client.post(
        f"{API}/customer/orders/{order_id}/advance",
        headers=seed["owner_auth"], json={"status": status})


async def _second_outlet(db, seed):
    """A second outlet with its own staff user, for cross-outlet scoping."""
    tag = uuid.uuid4().hex[:8]
    oid, uid = uuid.uuid4(), uuid.uuid4()
    org = await db.scalar(text(
        "SELECT organization_id FROM outlets WHERE id = :o"),
        {"o": seed["outlet_id"]})
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city,
                             is_visible, upi_id, geofence_radius_meters,
                             verification_status, created_at)
        VALUES (:i,:o,:n,'Testville', true, 'x@upi', 150, 'active', now())"""),
        {"i": str(oid), "o": str(org), "n": f"Other {tag}"})
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i,:u,:h, true, :o, now())"""),
        {"i": str(uid), "u": f"other_{tag}",
         "h": get_password_hash("correct-horse"), "o": str(oid)})
    await db.commit()
    return {
        "outlet_id": str(oid),
        "auth": {"Authorization":
                 f"Bearer {create_access_token(subject=f'other_{tag}')}"},
    }


# ============================ 1. method resolution ===========================

class TestPaymentMethodResolution:
    """payment_methods_for is THE decision; everything else is downstream."""

    async def test_prepaid_only_is_the_default(self, db, seed):
        methods = await CarevoService.payment_methods_for(db, seed["outlet_id"])
        assert methods == [PAY_PREPAID]

    async def test_pickup_only_when_prepaid_disabled(self, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        methods = await CarevoService.payment_methods_for(db, seed["outlet_id"])
        assert methods == [PAY_AT_PICKUP]

    async def test_both_enabled_returns_both_in_order(self, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        methods = await CarevoService.payment_methods_for(db, seed["outlet_id"])
        assert methods == [PAY_PREPAID, PAY_AT_PICKUP]

    async def test_prepaid_withdrawn_when_no_gateway_is_selected(
            self, db, seed, monkeypatch):
        """PAYMENT_GATEWAY=unset is what "Cashfree switched off" looks like.

        An outlet that is prepaid-only then offers NOTHING — an empty list is a
        real answer, and the rollout order exists precisely because of it.
        """
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "unset")
        assert await CarevoService.payment_methods_for(db, seed["outlet_id"]) == []

        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        methods = await CarevoService.payment_methods_for(db, seed["outlet_id"])
        assert methods == [PAY_AT_PICKUP], "pay-at-pickup needs no gateway"

    async def test_unknown_outlet_offers_nothing(self, db):
        assert await CarevoService.payment_methods_for(db, uuid.uuid4()) == []

    async def test_surfaced_on_menu_and_outlets(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)

        m = await client.get(f"{API}/customer/menu/{seed['outlet_id']}",
                             headers=seed["customer_auth"])
        assert m.status_code == 200, m.text
        assert m.json()["payment_methods"] == [PAY_PREPAID, PAY_AT_PICKUP]

        o = await client.get(f"{API}/customer/outlets",
                             headers=seed["customer_auth"])
        assert o.status_code == 200, o.text
        mine = [x for x in o.json() if x["id"] == seed["outlet_id"]]
        assert mine and mine[0]["payment_methods"] == [PAY_PREPAID, PAY_AT_PICKUP]


# ====================== 2. the old-build refusal (CRITICAL) ==================

class TestOldBuildIsRefused:
    async def test_no_payment_method_at_pickup_only_outlet_409s_and_writes_nothing(
            self, client, db, seed):
        """An installed build sends no payment_method => it asks for prepaid.

        THE ASSERTION THAT MATTERS is the row count. A 409 that still left a
        CREATED order behind would mean the old app holds stock on an order it
        can never pay for.
        """
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)

        before = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id = :o"),
            {"o": seed["outlet_id"]})

        r = await _place(client, seed, method=None)
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "PAYMENT_METHOD_UNAVAILABLE"
        # The app renders detail["message"] verbatim, so it has to be prose.
        assert "update" in detail["message"].lower()
        assert detail["available"] == [PAY_AT_PICKUP]

        after = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id = :o"),
            {"o": seed["outlet_id"]})
        assert after == before, "a refused order must leave NO row"

        # And nothing was held.
        held = await db.scalar(text("""
            SELECT count(*) FROM stock_reservations sr
              JOIN customer_orders co ON co.id = sr.order_id
             WHERE co.outlet_id = :o"""), {"o": seed["outlet_id"]})
        assert held == 0

    async def test_explicit_prepaid_is_refused_the_same_way(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        r = await _place(client, seed, method=PAY_PREPAID)
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

    async def test_unknown_method_is_refused_not_a_422(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        r = await _place(client, seed, method="BITCOIN")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

    async def test_reserved_upi_manual_is_never_offered(self, client, db, seed):
        """'UPI_MANUAL' exists in the DB CHECK but nothing writes or offers it."""
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        r = await _place(client, seed, method="UPI_MANUAL")
        assert r.status_code == 409
        assert PAY_AT_PICKUP in r.json()["detail"]["available"]


# ============================= 3. placement ==================================

class TestPlacement:
    async def test_pay_at_pickup_order_shape(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)

        # No gateway session, and the field is absent rather than faked.
        assert order["payment"] is None
        assert order["payment_mode"] == PAY_AT_PICKUP
        assert order["amount_due_at_pickup"] == order["final_amount"] == 200.0

        row = await _order_row(db, order["id"])
        assert row.status == "CREATED"
        assert row.payment_status == "PENDING"
        assert row.payment_mode == PAY_AT_PICKUP
        assert row.acceptance_state == AWAITING
        assert row.acceptance_deadline_at is not None
        assert row.call_state == "PENDING"
        assert row.call_attempts == 0
        # Pickup code is NOT minted at placement.
        assert row.pickup_code is None

        # The contact SNAPSHOT, from the account — never the request body.
        cust = (await db.execute(text(
            "SELECT name, phone_number FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})).first()
        assert row.contact_name == cust.name
        assert row.contact_phone == cust.phone_number

        # No payment transaction exists yet — there is nothing to charge.
        assert await _txns(db, order["id"]) == []

    async def test_no_gateway_order_is_created(self, client, db, seed, monkeypatch):
        """Proves the gateway is not merely unused but unreachable on this path."""
        from app.modules.carevo_payments import gateway as gw_mod

        called = []

        async def _boom(*a, **k):
            called.append(1)
            raise AssertionError("the gateway must not be called")

        monkeypatch.setattr(gw_mod.StubRazorpayGateway, "create_order", _boom)
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        await _place_ok(client, seed)
        assert called == []

    async def test_clock_uses_call_window_not_acceptance_timeout(
            self, client, db, seed):
        """A phone call window, not a tablet-tap window."""
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True,
                           call_window_s=120)
        await db.execute(text(
            "UPDATE outlets SET acceptance_timeout_s = 900 WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()

        order = await _place_ok(client, seed)
        row = await _order_row(db, order["id"])
        created = await db.scalar(text(
            "SELECT created_at FROM customer_orders WHERE id = :i"),
            {"i": order["id"]})
        window = (row.acceptance_deadline_at - created).total_seconds()
        assert 100 <= window <= 140, f"expected ~120s, got {window}"

    async def test_order_created_event_records_the_mode(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        payload = await db.scalar(text("""
            SELECT payload FROM order_events
             WHERE order_id = :i AND event_type = 'ORDER_CREATED'"""),
            {"i": order["id"]})
        assert payload["payment_mode"] == PAY_AT_PICKUP

    async def test_customer_status_endpoint_hides_contact(self, client, db, seed):
        """The customer already knows their number; echoing it adds nothing."""
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)

        r = await client.get(f"{API}/customer/orders/{order['id']}",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payment_mode"] == PAY_AT_PICKUP
        assert body["amount_due_at_pickup"] == 200.0
        assert body["call_state"] == "PENDING"
        assert "contact_phone" not in body
        assert "contact_name" not in body


# ======================== 4. the phone requirement ===========================

class TestVerifiedPhoneRequired:
    @pytest.fixture
    async def phoneless(self, db):
        """A Google-only account: no phone (nullable since migration 008)."""
        from app.modules.carevo_customer.deps import create_customer_token
        cid = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO customers (id, name, google_uid, points_balance, created_at)
            VALUES (:i, 'Googler', :g, 0, now())"""),
            {"i": str(cid), "g": f"guid-{uuid.uuid4().hex[:12]}"})
        await db.commit()
        return {"customer_id": str(cid),
                "customer_auth": {"Authorization":
                                  f"Bearer {create_customer_token(str(cid))}"}}

    async def test_not_offered_without_a_verified_phone(self, db, seed, phoneless):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        cust = (await db.execute(text(
            "SELECT * FROM customers WHERE id = :i"),
            {"i": phoneless["customer_id"]})).first()
        methods = await CarevoService.payment_methods_for(
            db, seed["outlet_id"], cust)
        assert methods == [PAY_PREPAID]

    async def test_forced_request_is_refused_with_a_usable_message(
            self, client, db, seed, phoneless):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        r = await client.post(f"{API}/customer/orders",
                             headers=phoneless["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "payment_method": PAY_AT_PICKUP,
        })
        assert r.status_code == 409, r.text
        assert "mobile number" in r.json()["detail"]["message"]


# ================================ 5. the call ================================

class TestCall:
    @pytest.fixture
    async def placed(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        return await _place_ok(client, seed)

    async def test_call_marks_state_and_counts_up(self, client, db, seed, placed):
        r = await client.post(f"{API}/pos/orders/{placed['id']}/call",
                              headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["call_state"] == "CALLED"
        assert r.json()["call_attempts"] == 1

        row = await _order_row(db, placed["id"])
        assert row.call_state == "CALLED"
        assert row.call_attempts == 1
        assert row.first_call_at is not None
        first = row.first_call_at

        # Ringing twice is normal, not an error.
        r2 = await client.post(f"{API}/pos/orders/{placed['id']}/call",
                               headers=seed["owner_auth"])
        assert r2.status_code == 200
        assert r2.json()["call_attempts"] == 2
        row2 = await _order_row(db, placed["id"])
        assert row2.first_call_at == first, "first_call_at must not move"

        assert ("ORDER_CALL_PLACED", "staff", "tap") in await _events(
            db, placed["id"])

    async def test_call_does_not_extend_the_deadline(self, client, db, seed, placed):
        before = (await _order_row(db, placed["id"])).acceptance_deadline_at
        await client.post(f"{API}/pos/orders/{placed['id']}/call",
                          headers=seed["owner_auth"])
        after = (await _order_row(db, placed["id"])).acceptance_deadline_at
        assert after == before, "a call is not a decision"

    async def test_call_404s_for_a_prepaid_order(self, client, db, seed, paid_order):
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/call",
                              headers=seed["owner_auth"])
        assert r.status_code == 404


# =============================== 6. accept ===================================

class TestAccept:
    async def test_accept_mints_code_commits_stock_and_receives(
            self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        # Track stock so there is a reservation to observe.
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()

        order = await _place_ok(client, seed)
        assert await _stock_states(db, order["id"]) == ["HELD"]
        assert (await _order_row(db, order["id"])).pickup_code is None

        r = await _accept(client, seed, order["id"], prep=20)
        assert r.status_code == 200, r.text
        assert r.json()["acceptance_state"] == "ACCEPTED"
        assert r.json()["status"] == "RECEIVED"

        row = await _order_row(db, order["id"])
        assert row.status == "RECEIVED"
        assert row.acceptance_state == "ACCEPTED"
        # The code appears HERE and not before.
        assert row.pickup_code and len(row.pickup_code) == 6
        # Still unpaid — the money comes at the counter.
        assert row.payment_status == "PENDING"
        # And the hold is now a spend, so the sweeper cannot reclaim it.
        assert await _stock_states(db, order["id"]) == ["COMMITTED"]

    async def test_committed_stock_survives_the_sweeper(self, client, db, seed):
        """The bug this closes: an unpaid order's hold lapsing mid-cook."""
        from app.modules.carevo_customer.stock import StockService

        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()

        order = await _place_ok(client, seed)
        await _accept(client, seed, order["id"])

        # Force every hold past its expiry, then sweep.
        await db.execute(text(
            "UPDATE stock_reservations SET expires_at = now() - interval '1 hour' "
            "WHERE order_id = :i"), {"i": order["id"]})
        await db.commit()
        await StockService.sweep_expired(db, outlet_id=seed["outlet_id"])

        assert await _stock_states(db, order["id"]) == ["COMMITTED"]
        left = await db.scalar(text(
            "SELECT stock_remaining FROM menu_items WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        assert left == 8, "units must stay spent while the food is being made"

    async def test_accept_404s_cross_outlet(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        other = await _second_outlet(db, seed)
        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              headers=other["auth"], json={"prep_minutes": 15})
        assert r.status_code == 404


# ========================== 7. reject / unreachable ==========================

class TestRejectAndUnreachable:
    @pytest.fixture
    async def placed(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        return await _place_ok(client, seed)

    async def test_reject_from_created_releases_stock_and_flags_no_refund(
            self, client, db, seed, placed):
        r = await client.post(f"{API}/pos/orders/{placed['id']}/reject",
                              headers=seed["owner_auth"],
                              json={"reason": "Too busy"})
        assert r.status_code == 200, r.text

        row = await _order_row(db, placed["id"])
        assert row.status == "CANCELLED"
        assert row.refund_required is False, "nothing was ever charged"
        assert row.refund_reason is None
        assert await _stock_states(db, placed["id"]) == ["RELEASED"]
        left = await db.scalar(text(
            "SELECT stock_remaining FROM menu_items WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        assert left == 10

    async def test_unreachable_records_its_own_cause(self, client, db, seed, placed):
        await client.post(f"{API}/pos/orders/{placed['id']}/call",
                          headers=seed["owner_auth"])
        r = await client.post(f"{API}/pos/orders/{placed['id']}/reject",
                              headers=seed["owner_auth"],
                              json={"reason": "No answer", "unreachable": True})
        assert r.status_code == 200, r.text

        row = await _order_row(db, placed["id"])
        assert row.status == "CANCELLED"
        assert row.call_state == "UNREACHABLE"
        assert row.refund_required is False

        kinds = [e[0] for e in await _events(db, placed["id"])]
        assert "ORDER_REJECTED" in kinds
        assert "ORDER_CALL_UNREACHABLE" in kinds

    async def test_created_is_not_rejectable_for_a_prepaid_order(
            self, client, db, seed):
        """The widening is per-order, so a prepaid checkout cannot be cancelled
        out from under the customer."""
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=False)
        order = await _place_ok(client, seed, method=PAY_PREPAID)
        assert (await _order_row(db, order["id"])).status == "CREATED"

        r = await client.post(f"{API}/pos/orders/{order['id']}/reject",
                              headers=seed["owner_auth"], json={})
        assert r.status_code == 409, r.text


# ======================== 8. expiry (CRITICAL: no refund) ====================

class TestExpiryFlagsNoRefund:
    async def test_expired_pickup_order_owes_nothing(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True,
                           call_window_s=60)
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        order = await _place_ok(client, seed)

        # Drive the deadline into the past, then sweep.
        await db.execute(text(
            "UPDATE customer_orders SET acceptance_deadline_at = "
            "now() - interval '1 minute' WHERE id = :i"), {"i": order["id"]})
        await db.commit()
        res = await AcceptanceService.process_acceptance_deadlines(
            db, order_id=order["id"])
        assert res["expired"] == 1

        row = await _order_row(db, order["id"])
        assert row.acceptance_state == EXPIRED
        assert row.status == "CANCELLED"
        # THE ASSERTION: no money moved, so no refund is owed.
        assert row.refund_required is False
        assert row.refund_reason is None
        assert await _stock_states(db, order["id"]) == ["RELEASED"]

    async def test_expired_prepaid_order_still_flags_a_refund(
            self, client, db, seed, paid_order):
        """The conditional must not have broken the case it was built for."""
        await db.execute(text("""
            UPDATE customer_orders
               SET acceptance_state = 'AWAITING',
                   acceptance_deadline_at = now() - interval '1 minute'
             WHERE id = :i"""), {"i": paid_order["id"]})
        await db.commit()

        res = await AcceptanceService.process_acceptance_deadlines(
            db, order_id=paid_order["id"])
        assert res["expired"] == 1

        row = await _order_row(db, paid_order["id"])
        assert row.status == "CANCELLED"
        assert row.refund_required is True
        assert row.refund_reason == "acceptance_expired"

    async def test_expiry_counts_an_outlet_strike(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        await db.execute(text(
            "UPDATE customer_orders SET acceptance_deadline_at = "
            "now() - interval '1 minute' WHERE id = :i"), {"i": order["id"]})
        await db.commit()
        await AcceptanceService.process_acceptance_deadlines(
            db, order_id=order["id"])
        strikes = await db.scalar(text(
            "SELECT consecutive_expiries FROM outlets WHERE id = :o"),
            {"o": seed["outlet_id"]})
        assert strikes == 1


# =============================== 9. collect ==================================

class TestCollect:
    @pytest.fixture
    async def ready(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        await _accept(client, seed, order["id"])
        await _advance(client, seed, order["id"], "PREPARING")
        await _advance(client, seed, order["id"], "READY")
        row = await _order_row(db, order["id"])
        return {"id": order["id"], "code": row.pickup_code}

    @pytest.mark.parametrize("method", ["cash", "upi"])
    async def test_collect_records_payment_and_completes(
            self, client, db, seed, ready, method):
        r = await client.post(
            f"{API}/pos/orders/{ready['id']}/collect",
            headers=seed["owner_auth"],
            json={"pickup_code": ready["code"], "method": method})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["collected"] is True
        assert body["status"] == "COMPLETED"
        assert body["payment_status"] == "PAID"
        assert body["collected_payment_method"] == method

        row = await _order_row(db, ready["id"])
        assert row.status == "COMPLETED"
        assert row.payment_status == "PAID"
        assert row.collected_payment_method == method
        assert row.collected_at is not None
        assert str(row.collected_by) == seed["owner_id"], "who took the money"

        # One counter transaction, in the same ledger as every gateway payment.
        assert await _txns(db, ready["id"]) == [
            ("counter", method, "PAID", 200.0)]

        # Both events: ORDER_PAID for every existing reader, PAYMENT_COLLECTED
        # for what it cannot carry.
        kinds = [e[0] for e in await _events(db, ready["id"])]
        assert "ORDER_PAID" in kinds
        assert "PAYMENT_COLLECTED" in kinds
        assert "PICKUP_VERIFIED" in kinds

        # Loyalty accrued, exactly as a gateway payment would have.
        pts = await db.scalar(text(
            "SELECT points_balance FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})
        assert float(pts) > 0

    async def test_wrong_code_takes_no_money_and_closes_nothing(
            self, client, db, seed, ready):
        r = await client.post(
            f"{API}/pos/orders/{ready['id']}/collect",
            headers=seed["owner_auth"],
            json={"pickup_code": "000000", "method": "cash"})
        assert r.status_code == 200, r.text
        assert r.json()["collected"] is False
        assert r.json()["attempts_remaining"] == 2

        row = await _order_row(db, ready["id"])
        assert row.status == "READY"
        assert row.payment_status == "PENDING"
        assert row.collected_payment_method is None
        assert row.failed_attempts == 1
        assert await _txns(db, ready["id"]) == []

    async def test_three_wrong_codes_lock_the_order(self, client, db, seed, ready):
        for _ in range(3):
            await client.post(
                f"{API}/pos/orders/{ready['id']}/collect",
                headers=seed["owner_auth"],
                json={"pickup_code": "000000", "method": "cash"})
        row = await _order_row(db, ready["id"])
        assert row.is_locked is True

        r = await client.post(
            f"{API}/pos/orders/{ready['id']}/collect",
            headers=seed["owner_auth"],
            json={"pickup_code": ready["code"], "method": "cash"})
        assert r.status_code == 423

    async def test_bad_method_is_a_422(self, client, seed, ready):
        r = await client.post(
            f"{API}/pos/orders/{ready['id']}/collect",
            headers=seed["owner_auth"],
            json={"pickup_code": ready["code"], "method": "barter"})
        assert r.status_code == 422

    async def test_concurrent_collects_resolve_to_one_winner(
            self, client, db, seed, ready):
        """Compare-and-set on status: two tablets, one handover."""
        body = {"pickup_code": ready["code"], "method": "cash"}
        r1, r2 = await asyncio.gather(
            client.post(f"{API}/pos/orders/{ready['id']}/collect",
                        headers=seed["owner_auth"], json=body),
            client.post(f"{API}/pos/orders/{ready['id']}/collect",
                        headers=seed["owner_auth"], json=body),
            return_exceptions=True,
        )
        codes = sorted(
            getattr(r, "status_code", 500) for r in (r1, r2)
            if not isinstance(r, Exception))
        assert 200 in codes, (r1, r2)
        # Exactly one payment, however the race fell out.
        assert len(await _txns(db, ready["id"])) == 1

    async def test_collect_404s_cross_outlet(self, client, db, seed, ready):
        other = await _second_outlet(db, seed)
        r = await client.post(
            f"{API}/pos/orders/{ready['id']}/collect", headers=other["auth"],
            json={"pickup_code": ready["code"], "method": "cash"})
        assert r.status_code == 404


# =================== 10. the verify-pickup money guard (CRITICAL) ============

class TestVerifyPickupMoneyGuard:
    async def test_unpaid_pickup_order_cannot_be_verified(self, client, db, seed):
        """verify_pickup never reads payment_status. Without the guard this
        completes an order nobody paid for."""
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        await _accept(client, seed, order["id"])
        await _advance(client, seed, order["id"], "PREPARING")
        await _advance(client, seed, order["id"], "READY")
        code = (await _order_row(db, order["id"])).pickup_code

        r = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=seed["owner_auth"],
                              json={"order_id": order["id"],
                                    "pickup_code": code})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_NOT_RECORDED"

        row = await _order_row(db, order["id"])
        assert row.status == "READY", "the order must stay live"
        assert row.payment_status == "PENDING"

    async def test_verify_works_again_once_collected(self, client, db, seed):
        """A paid pickup order falls through untouched, so a second verify tap
        behaves like any other repeat verify."""
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        await _accept(client, seed, order["id"])
        await _advance(client, seed, order["id"], "READY")
        code = (await _order_row(db, order["id"])).pickup_code
        await client.post(f"{API}/pos/orders/{order['id']}/collect",
                          headers=seed["owner_auth"],
                          json={"pickup_code": code, "method": "cash"})

        r = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=seed["owner_auth"],
                              json={"order_id": order["id"],
                                    "pickup_code": code})
        assert r.status_code == 200, r.text

    async def test_prepaid_verify_is_untouched(self, client, db, seed, paid_order):
        code = (await _order_row(db, paid_order["id"])).pickup_code
        r = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=seed["owner_auth"],
                              json={"order_id": paid_order["id"],
                                    "pickup_code": code})
        assert r.status_code == 200, r.text
        assert r.json()["verified"] is True


# =============================== 11. no-show =================================

class TestNoShow:
    @pytest.fixture
    async def ready(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = 10 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        order = await _place_ok(client, seed)
        await _accept(client, seed, order["id"])
        await _advance(client, seed, order["id"], "READY")
        return order

    async def test_no_show_abandons_and_strikes_without_a_refund(
            self, client, db, seed, ready):
        r = await client.post(f"{API}/pos/orders/{ready['id']}/no-show",
                              headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ABANDONED"

        row = await _order_row(db, ready["id"])
        assert row.status == "ABANDONED"
        assert row.no_show_at is not None
        assert row.refund_required is False, "nothing was ever charged"
        assert row.payment_status == "PENDING"

        strikes = await db.scalar(text(
            "SELECT no_show_count FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})
        assert strikes == 1

        assert "ORDER_NO_SHOW" in [e[0] for e in await _events(db, ready["id"])]
        # Per the brief: committed units come back on a no-show.
        assert await _stock_states(db, ready["id"]) == ["RELEASED"]

    async def test_no_show_is_refused_before_the_food_is_made(
            self, client, db, seed):
        """An unconfirmed order is not a no-show; the call window owns it."""
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        r = await client.post(f"{API}/pos/orders/{order['id']}/no-show",
                              headers=seed["owner_auth"])
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "not_a_no_show"

    async def test_two_strikes_withdraw_pay_at_pickup(self, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        await db.execute(text(
            "UPDATE customers SET no_show_count = :n WHERE id = :i"),
            {"n": NO_SHOW_STRIKE_LIMIT, "i": seed["customer_id"]})
        await db.commit()
        cust = (await db.execute(text(
            "SELECT * FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})).first()
        assert await CarevoService.payment_methods_for(
            db, seed["outlet_id"], cust) == [PAY_PREPAID]

    async def test_no_show_404s_cross_outlet(self, client, db, seed, ready):
        other = await _second_outlet(db, seed)
        r = await client.post(f"{API}/pos/orders/{ready['id']}/no-show",
                              headers=other["auth"])
        assert r.status_code == 404


# ============================== 12. the abuse cap ============================

class TestOpenOrderCap:
    async def test_second_pickup_order_is_refused_with_a_deep_link(
            self, client, db, seed):
        """The id is the point: the app deep-links to the blocking order."""
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        first = await _place_ok(client, seed)

        r = await _place(client, seed)
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "OPEN_PICKUP_ORDER_PENDING"
        assert detail["order_id"] == first["id"]
        # The uuid stays out of the prose — it is data, not a sentence.
        assert first["id"] not in detail["message"]

    async def test_cap_still_names_the_order_when_both_methods_are_on(
            self, client, db, seed):
        """At a BOTH outlet the available list is non-empty, so this exercises
        the other route into the same refusal."""
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        first = await _place_ok(client, seed)

        r = await _place(client, seed)
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "OPEN_PICKUP_ORDER_PENDING"
        assert detail["order_id"] == first["id"]

    async def test_cap_applies_with_untracked_items(self, client, db, seed):
        """The existing hoarding cap only bites on stock-TRACKED items; this one
        must not depend on stock tracking at all."""
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = NULL WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)

        first = await _place_ok(client, seed)
        # THE PRECONDITION that makes this test mean something: with an
        # untracked item there is no reservation row at all, so the existing
        # stock-based cap has nothing to fire on.
        assert await _stock_states(db, first["id"]) == []

        r = await _place(client, seed)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "OPEN_PICKUP_ORDER_PENDING"

    async def test_cap_is_global_across_outlets(self, client, db, seed):
        """The risk is a person who never pays, not one restaurant's stock."""
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        first = await _place_ok(client, seed)

        other = await _second_outlet(db, seed)
        await _set_methods(db, other["outlet_id"], prepaid=False, pickup=True)

        r = await _place(client, seed, outlet_id=other["outlet_id"])
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        # The SPECIFIC refusal matters. The second outlet has no menu items of
        # its own, so an "Unknown menu item" 400 would also be a non-200 — and
        # would prove nothing about the cap. This pins that the cap fired, and
        # that it named the order at the OTHER outlet.
        assert detail["error"] == "OPEN_PICKUP_ORDER_PENDING"
        assert detail["order_id"] == first["id"]

    @pytest.mark.parametrize("resolve", ["collect", "reject"])
    async def test_cap_clears_once_the_order_is_resolved(
            self, client, db, seed, resolve):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        first = await _place_ok(client, seed)

        if resolve == "collect":
            await _accept(client, seed, first["id"])
            await _advance(client, seed, first["id"], "READY")
            code = (await _order_row(db, first["id"])).pickup_code
            await client.post(f"{API}/pos/orders/{first['id']}/collect",
                              headers=seed["owner_auth"],
                              json={"pickup_code": code, "method": "cash"})
        else:
            await client.post(f"{API}/pos/orders/{first['id']}/reject",
                              headers=seed["owner_auth"], json={})

        r = await _place(client, seed)
        assert r.status_code == 200, r.text

    async def test_prepaid_orders_do_not_block_a_pickup_order(
            self, client, db, seed, paid_order):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        r = await _place(client, seed)
        assert r.status_code == 200, r.text


# ====================== 13. owner payload + contact window ===================

class TestOwnerPayloadAndContact:
    async def _queue(self, client, seed, order_id):
        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        return next((o for o in r.json() if o["order_id"] == order_id), None)

    async def test_awaiting_order_is_on_the_queue_with_the_contact(
            self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)

        row = await self._queue(client, seed, order["id"])
        assert row is not None, "a CREATED pickup order must reach the tablet"
        assert row["status"] == "CREATED"
        assert row["payment_mode"] == PAY_AT_PICKUP
        assert row["acceptance_state"] == AWAITING
        assert row["call_state"] == "PENDING"
        assert row["contact_visible"] is True
        assert row["contact_phone"]
        # FIRST NAME ONLY — a surname has no use at a counter.
        full = await db.scalar(text(
            "SELECT name FROM customers WHERE id = :i"),
            {"i": seed["customer_id"]})
        assert row["contact_first_name"] == full.split()[0]

    async def test_prepaid_rows_carry_no_contact_at_all(
            self, client, seed, paid_order):
        """The name-free guarantee still holds everywhere it held before."""
        row = await self._queue(client, seed, paid_order["id"])
        assert row is not None
        assert row["payment_mode"] == "PREPAID"
        assert row["contact_first_name"] is None
        assert row["contact_phone"] is None
        assert row["contact_visible"] is False
        assert row["call_state"] is None

    async def _visible_contact(self, db, seed, order_id):
        """What the visibility SQL would return for one order, via a COMPLETED
        row inside its grace window so the queue actually carries it."""
        rows = await CarevoService.list_active_orders(db, seed["outlet_id"])
        row = next((o for o in rows
                    if str(o["order_id"]) == str(order_id)), None)
        return row

    async def test_contact_is_suppressed_once_the_grace_window_closes(
            self, client, db, seed):
        """Visible while live and for 2h after it finishes, then withheld.

        Driven through a COLLECTED order, because a COMPLETED row stays on the
        queue for its own 30-minute grace and is therefore the one terminal
        state where both sides of the contact window are observable.
        """
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        await _accept(client, seed, order["id"])
        await _advance(client, seed, order["id"], "READY")
        code = (await _order_row(db, order["id"])).pickup_code
        await client.post(f"{API}/pos/orders/{order['id']}/collect",
                          headers=seed["owner_auth"],
                          json={"pickup_code": code, "method": "cash"})

        # INSIDE both windows: the contact is readable for the callback.
        row = await self._visible_contact(db, seed, order["id"])
        assert row is not None, "a just-collected order stays on the queue"
        assert row["contact_visible"] is True
        assert row["contact_phone"]

        # Age the order past the CONTACT window but keep it inside the
        # COMPLETED_GRACE window, so it is still on the queue and the only
        # thing that has changed is contact visibility.
        await db.execute(text(
            "UPDATE customer_orders "
            "   SET updated_at = now() - interval '3 hours', "
            "       pickup_verified_at = now() - interval '5 minutes' "
            " WHERE id = :i"), {"i": order["id"]})
        await db.commit()

        row = await self._visible_contact(db, seed, order["id"])
        assert row is not None, "still inside COMPLETED_GRACE"
        assert row["contact_visible"] is False, "past the 2h contact window"
        assert row["contact_phone"] is None
        assert row["contact_first_name"] is None

        # SUPPRESSED, NOT DESTROYED — the row still holds it until the sweep.
        stored = await _order_row(db, order["id"])
        assert stored.contact_phone is not None
        assert stored.contact_redacted_at is None

    async def test_redaction_sweep_destroys_the_snapshot(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)

        # Age the order past retention. The CAST is required: without it the
        # bind is read as an untyped literal and `now() - :age - interval` is
        # parsed as `now() - (:age - interval)`, which is an interval, not a
        # timestamp.
        await db.execute(text(
            "UPDATE customer_orders "
            "   SET created_at = now() - CAST(:age AS interval) "
            "                           - interval '1 day' "
            " WHERE id = :i"),
            {"age": CONTACT_REDACTION_AFTER, "i": order["id"]})
        await db.commit()

        n = await CarevoService.redact_expired_contacts(
            db, outlet_id=seed["outlet_id"])
        assert n == 1

        row = await _order_row(db, order["id"])
        assert row.contact_phone is None
        assert row.contact_name is None
        assert row.contact_redacted_at is not None

        # Idempotent.
        assert await CarevoService.redact_expired_contacts(
            db, outlet_id=seed["outlet_id"]) == 0

    async def test_another_outlet_never_sees_the_contact(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        other = await _second_outlet(db, seed)

        r = await client.get(f"{API}/pos/orders", headers=other["auth"])
        assert r.status_code == 200, r.text
        ids = [o["order_id"] for o in r.json()]
        assert order["id"] not in ids
        body = r.text
        phone = (await _order_row(db, order["id"])).contact_phone
        assert phone and phone not in body

    async def test_lookup_pickup_never_returns_a_contact(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True)
        order = await _place_ok(client, seed)
        await _accept(client, seed, order["id"])
        code = (await _order_row(db, order["id"])).pickup_code

        r = await client.post(f"{API}/pos/orders/lookup-pickup",
                              headers=seed["owner_auth"],
                              json={"pickup_code": code})
        assert r.status_code == 200, r.text
        found = r.json()
        assert found["found"] is True
        assert found["order"]["payment_mode"] == PAY_AT_PICKUP
        assert found["order"]["contact_phone"] is None
        assert found["order"]["contact_first_name"] is None


# ===================== 14. the stock-hold coupling (CRITICAL) ================

class TestCallWindowFitsStockHold:
    def test_call_window_ceiling_stays_below_the_stock_hold(self):
        """540 < 600 is not a coincidence and must not become one.

        If STOCK_HOLD_TTL_SECONDS is ever lowered below the call-window
        ceiling, a pay-at-pickup order's hold lapses while the customer is
        still waiting for the phone to ring — and the dish reads as available
        to everyone else while somebody's unconfirmed order sits on it.
        """
        CEILING = 540  # ck_outlets_call_window
        assert CEILING < settings.STOCK_HOLD_TTL_SECONDS, (
            f"call_window_s ceiling ({CEILING}s) must stay below "
            f"STOCK_HOLD_TTL_SECONDS ({settings.STOCK_HOLD_TTL_SECONDS}s)")

    async def test_the_database_refuses_a_window_past_the_ceiling(self, db, seed):
        with pytest.raises(Exception):
            await db.execute(text(
                "UPDATE outlets SET call_window_s = 601 WHERE id = :o"),
                {"o": seed["outlet_id"]})
            await db.commit()
        await db.rollback()

    async def test_default_window_leaves_headroom(self, db, seed):
        w = await AcceptanceService.call_window_s(db, seed["outlet_id"])
        assert w == 300
        assert w < settings.STOCK_HOLD_TTL_SECONDS


# ============================= 15. the admin route ===========================

class TestAdminPaymentMethods:
    async def test_super_admin_can_flip_one_outlet(self, client, db, seed):
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": False, "pay_at_pickup": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payment_prepaid_enabled"] is False
        assert body["payment_pay_at_pickup_enabled"] is True
        assert body["effective_methods"] == [PAY_AT_PICKUP]

        row = (await db.execute(text(
            "SELECT payment_prepaid_enabled, payment_pay_at_pickup_enabled "
            "FROM outlets WHERE id = :o"), {"o": seed["outlet_id"]})).first()
        assert (row[0], row[1]) == (False, True)

    async def test_both_false_is_a_422(self, client, seed):
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": False, "pay_at_pickup": False})
        assert r.status_code == 422, r.text

    async def test_the_database_refuses_both_false_too(self, db, seed):
        """The UI is never the enforcement point."""
        with pytest.raises(Exception):
            await db.execute(text(
                "UPDATE outlets SET payment_prepaid_enabled = false, "
                "payment_pay_at_pickup_enabled = false WHERE id = :o"),
                {"o": seed["outlet_id"]})
            await db.commit()
        await db.rollback()

    async def test_unknown_outlet_is_a_404(self, client, seed):
        r = await client.patch(
            f"{API}/admin/outlets/{uuid.uuid4()}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": True})
        assert r.status_code == 404

    async def test_staff_cannot_flip_it(self, client, seed):
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["owner_auth"],
            json={"prepaid": True, "pay_at_pickup": True})
        assert r.status_code in (401, 403)

    async def test_switching_does_not_touch_orders_in_flight(
            self, client, db, seed, paid_order):
        """An order carries its own payment_mode from creation."""
        await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": False, "pay_at_pickup": True})
        row = await _order_row(db, paid_order["id"])
        assert row.payment_mode == "PREPAID"
        assert row.payment_status == "PAID"


# ====================== 16. prepaid regression (CRITICAL) ====================

class TestPrepaidRegression:
    async def test_the_whole_prepaid_flow_is_unchanged(self, client, db, seed):
        """CREATED -> PAID -> RECEIVED -> READY -> verify -> COMPLETED, with a
        gateway session throughout and not one 034 field set."""
        order = await _place_ok(client, seed, method=None)

        # A real payment block, exactly as before.
        assert order["payment"] is not None
        assert order["payment"]["gateway"] == "razorpay"
        assert order["payment"]["gateway_order_id"]
        assert order["payment_mode"] == "PREPAID"
        assert order["amount_due_at_pickup"] == 0

        row = await _order_row(db, order["id"])
        assert row.payment_mode == "PREPAID"
        assert row.contact_name is None and row.contact_phone is None
        assert row.call_state is None and row.call_attempts == 0

        p = await client.post(f"{API}/customer/payment/simulate",
                              headers=seed["customer_auth"],
                              json={"order_id": order["id"], "method": "upi"})
        assert p.status_code == 200, p.text

        row = await _order_row(db, order["id"])
        assert row.payment_status == "PAID"
        assert row.pickup_code, "mark_paid still mints the code for prepaid"

        await _advance(client, seed, order["id"], "RECEIVED")
        await _advance(client, seed, order["id"], "READY")

        v = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=seed["owner_auth"],
                              json={"order_id": order["id"],
                                    "pickup_code": row.pickup_code})
        assert v.status_code == 200, v.text
        assert v.json()["verified"] is True
        assert (await _order_row(db, order["id"])).status == "COMPLETED"

    async def test_prepaid_order_has_a_gateway_transaction(
            self, client, db, seed):
        order = await _place_ok(client, seed, method=None)
        txns = await _txns(db, order["id"])
        assert len(txns) == 1
        assert txns[0][0] == "razorpay"
        assert txns[0][2] == "CREATED"

    async def test_explicit_prepaid_matches_the_implicit_default(
            self, client, db, seed):
        a = await _place_ok(client, seed, method=None)
        # Resolve the first so the (prepaid) order does not block anything.
        b = await _place_ok(client, seed, method=PAY_PREPAID)
        ra, rb = await _order_row(db, a["id"]), await _order_row(db, b["id"])
        assert ra.payment_mode == rb.payment_mode == "PREPAID"
