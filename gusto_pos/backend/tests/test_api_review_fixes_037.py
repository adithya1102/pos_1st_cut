"""The defects the independent review of 5d03ea83 confirmed, each pinned.

One class per finding. Every test here failed before its fix — the fixes are
listed against the tests in the commit message — and each is written against
observable behaviour (a status code, a list membership, a column value) rather
than against the shape of the code that implements it.

THE THREE THAT MOVE MONEY
-------------------------
* `TestDirectUpiNeverEntersTheCashfreeQueue` — CareVo was never in the payment
  path for a direct-UPI order, so it cannot reverse one. Listing it on the
  gateway refund worklist promises a customer a refund nobody is able to send.

* `TestExpiryAfterAClaimHasAResolution` — an expired claim cancels the order
  with `manual_refund_due = true` on purpose (nobody looked, so an honest
  customer must not be stranded). Without a way for the restaurant to say the
  money never arrived, that leaves a shop owing a refund on a payment it never
  received, and a false claimant with no strike.

* `TestPartialPatchDoesNotEraseSavedFields` — a PATCH carrying only the three
  toggles was erasing `upi_vpa`. The VPA is where customers' money goes; a
  screen that silently drops it turns an unrelated edit into an outage, and a
  re-entered typo into a payment to a stranger.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.security import get_password_hash
from app.modules.carevo_customer.acceptance import AcceptanceService
from app.modules.carevo_customer.service import (
    FALSE_CLAIM_STRIKE_LIMIT, PAY_AT_PICKUP, PAY_PREPAID, PAY_UPI_MANUAL,
    CarevoService,
)
from tests.conftest import API

SETTINGS = f"{API}/pos/outlet/payment-methods"
REFUND_DUE = f"{API}/admin/orders/refund-due"

VPA = "testrestaurant@okaxis"
PAYEE = "Test Kitchen"


# ------------------------------- helpers -------------------------------------

async def _enable_upi(db, outlet_id, *, prepaid=False, pickup=False):
    await db.execute(text("""
        UPDATE outlets SET payment_prepaid_enabled = :p,
                           payment_pay_at_pickup_enabled = :k,
                           payment_upi_manual_enabled = true,
                           upi_vpa = :v, upi_payee_name = :n,
                           upi_attested_at = now(),
                           is_manually_closed = false
         WHERE id = :o"""),
        {"p": prepaid, "k": pickup, "v": VPA, "n": PAYEE,
         "o": str(outlet_id)})
    await db.commit()


async def _place(client, seed, *, method=PAY_UPI_MANUAL, qty=2):
    r = await client.post(f"{API}/customer/orders",
                          headers=seed["customer_auth"],
                          json={"outlet_id": seed["outlet_id"],
                                "payment_method": method,
                                "items": [{"menu_item_id": seed["menu_item_id"],
                                           "quantity": qty}]})
    assert r.status_code == 200, r.text
    return r.json()


async def _claim(client, seed, oid):
    r = await client.post(f"{API}/customer/orders/{oid}/claim-paid",
                          headers=seed["customer_auth"])
    assert r.status_code == 200, r.text
    return r.json()


async def _accept(client, seed, oid, *, auth=None, prep=15):
    return await client.post(f"{API}/pos/orders/{oid}/accept",
                             headers=auth or seed["owner_auth"],
                             json={"prep_minutes": prep})


async def _reject(client, seed, oid, outcome=None, *, reason=None):
    """`upi_outcome` is its own field — `reason` is free text and does NOT
    select the direct-UPI branch, which is what makes the two outcomes
    distinguishable."""
    body = {}
    if reason is not None:
        body["reason"] = reason
    if outcome is not None:
        body["upi_outcome"] = outcome
    return await client.post(f"{API}/pos/orders/{oid}/reject",
                             headers=seed["owner_auth"], json=body)


async def _row(db, oid):
    await db.rollback()
    return (await db.execute(text("""
        SELECT status, payment_status, payment_mode, acceptance_state,
               refund_required, refund_reason, manual_refund_due,
               manual_refund_reason, pickup_code, payment_claimed_at
          FROM customer_orders WHERE id = :i"""), {"i": str(oid)})).first()


async def _in_refund_queue(client, seed, oid) -> bool:
    r = await client.get(f"{REFUND_DUE}?limit=500", headers=seed["admin_auth"])
    assert r.status_code == 200, r.text
    return str(oid) in {str(x["order_id"]) for x in r.json()}


async def _strikes(db, customer_id) -> int:
    await db.rollback()
    return await db.scalar(text(
        "SELECT false_claim_count FROM customers WHERE id = :i"),
        {"i": str(customer_id)}) or 0


async def _age_claim(db, oid, *, minutes):
    """Backdate every clock the sweeps read, so the order is genuinely old."""
    await db.execute(text("""
        UPDATE customer_orders
           SET payment_claimed_at = payment_claimed_at - (:m || ' minutes')::interval,
               created_at = created_at - (:m || ' minutes')::interval
         WHERE id = :i"""), {"m": str(minutes), "i": str(oid)})
    await db.commit()


async def _outlet_payment_row(db, outlet_id):
    await db.rollback()
    return (await db.execute(text("""
        SELECT payment_prepaid_enabled, payment_pay_at_pickup_enabled,
               payment_upi_manual_enabled, cashfree_unlocked, upi_vpa,
               upi_payee_name, upi_attested_at
          FROM outlets WHERE id = :i"""), {"i": str(outlet_id)})).first()


async def _staff(db, outlet_id, role_name=None, *, owner_flag=True):
    tag = uuid.uuid4().hex[:8]
    uid = uuid.uuid4()
    username = f"s_{tag}"
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           is_outlet_owner, created_at)
        VALUES (:i,:u,:h, true, :o, :f, now())"""),
        {"i": str(uid), "u": username, "f": owner_flag,
         "h": get_password_hash("correct-horse"), "o": str(outlet_id)})
    await db.commit()
    return {"auth": {"Authorization":
                     f"Bearer {create_access_token(subject=username)}"}}


async def _second_outlet_with_upi(db, seed):
    oid = uuid.uuid4()
    org = await db.scalar(text(
        "SELECT organization_id FROM outlets WHERE id = :o"),
        {"o": seed["outlet_id"]})
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city,
                             is_visible, upi_id, geofence_radius_meters,
                             verification_status, created_at,
                             cashfree_unlocked)
        VALUES (:i,:o,:n,'T', true, 'x@upi', 150, 'active', now(), true)"""),
        {"i": str(oid), "o": str(org), "n": f"Other {uuid.uuid4().hex[:8]}"})
    menu, cat, item = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(text("""
        INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at)
        VALUES (:i,:o,'v1',true, now())"""), {"i": str(menu), "o": str(oid)})
    await db.execute(text("""
        INSERT INTO categories (id, menu_id, name, created_at)
        VALUES (:i,:m,'Mains', now())"""), {"i": str(cat), "m": str(menu)})
    await db.execute(text("""
        INSERT INTO menu_items (id, category_id, name, base_price, is_veg,
                                is_active, is_available, created_at)
        VALUES (:i,:c,'Dish B', 100, true, true, true, now())"""),
        {"i": str(item), "c": str(cat)})
    await db.commit()
    await _enable_upi(db, oid)
    staff = await _staff(db, oid)
    return {"outlet_id": str(oid), "menu_item_id": str(item), **staff}


# ============ FINDING 2: direct UPI must never reach the gateway queue =======

class TestDirectUpiNeverEntersTheCashfreeQueue:
    """`/admin/orders/refund-due` is the CASHFREE worklist — an admin works it
    by issuing gateway refunds. A direct-UPI payment went from the customer's
    bank to the restaurant's VPA with CareVo nowhere in it, so there is no
    gateway transaction to reverse and nothing an admin on that screen can do.

    The two axes are separate on purpose: `refund_required` means CareVo owes a
    gateway refund, `manual_refund_due` means the RESTAURANT owes the customer
    their money back directly. A direct-UPI order must only ever set the second.
    """

    async def test_a_rejected_paid_upi_order_owes_manually_not_via_gateway(
            self, client, db, seed):
        await _enable_upi(db, seed["outlet_id"])
        order = await _place(client, seed)
        await _claim(client, seed, order["id"])
        assert (await _accept(client, seed, order["id"])).status_code == 200

        # Accepted means the restaurant CONFIRMED the money arrived, so this
        # is the worst case: a paid order the restaurant then cannot fulfil.
        r = await _reject(client, seed, order["id"], "cannot_make")
        assert r.status_code == 200, r.text

        row = await _row(db, order["id"])
        assert row.payment_status == "PAID"
        assert row.payment_mode == PAY_UPI_MANUAL
        assert row.manual_refund_due is True, \
            "the restaurant owes this customer their money back"
        assert row.refund_required is False, \
            "CareVo cannot reverse a payment it never touched"
        assert not await _in_refund_queue(client, seed, order["id"]), \
            "a direct-UPI order must never appear on the gateway worklist"

    async def test_a_prepaid_order_still_does_reach_the_queue(
            self, client, db, seed, paid_order):
        """The control. The guard must be narrowed to direct UPI, not disabled
        — a real gateway refund still has to be worked."""
        # A gateway order has no upi_outcome — this is an ordinary reject.
        r = await _reject(client, seed, paid_order["id"],
                          reason="cannot_make")
        assert r.status_code == 200, r.text
        row = await _row(db, paid_order["id"])
        assert row.payment_mode == PAY_PREPAID
        assert row.refund_required is True
        assert await _in_refund_queue(client, seed, paid_order["id"])

    async def test_the_ttl_sweep_does_not_queue_a_direct_upi_order(
            self, client, db, seed):
        """The other path into the queue. An accepted-and-paid order that the
        customer never collects is swept to a terminal status, and that sweep
        used to set refund_required without looking at payment_mode.
        """
        await _enable_upi(db, seed["outlet_id"])
        order = await _place(client, seed)
        await _claim(client, seed, order["id"])
        assert (await _accept(client, seed, order["id"])).status_code == 200

        before_strikes = await _strikes(db, seed["customer_id"])
        # _expire_stale_pickups keys off updated_at with release_at NULL —
        # not off a "ready" timestamp, which this table does not have.
        await _age_claim(db, order["id"],
                         minutes=settings.PICKUP_TTL_MINUTES + 120)
        await db.execute(text("""
            UPDATE customer_orders
               SET updated_at = now() - (:m || ' minutes')::interval,
                   accepted_at = now() - (:m || ' minutes')::interval,
                   release_at = NULL
             WHERE id = :i"""),
            {"m": str(settings.PICKUP_TTL_MINUTES + 120),
             "i": str(order["id"])})
        await db.commit()

        # Any staff read runs the sweep; this is the check-on-read pattern.
        await CarevoService.expire_unclaimed_upi_orders(
            db, outlet_id=uuid.UUID(seed["outlet_id"]))
        await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])

        assert not await _in_refund_queue(client, seed, order["id"]), \
            "the TTL sweep must not put a direct-UPI order on the queue"
        row = await _row(db, order["id"])
        assert row.refund_required is False
        # And no strike: the customer said they paid and the restaurant AGREED,
        # so a no-show here is not a false claim.
        assert await _strikes(db, seed["customer_id"]) == before_strikes


# ============ FINDING 3: an expired claim has a resolution path =============

class TestExpiryAfterAClaimHasAResolution:
    """POST /pos/orders/{id}/payment-not-received."""

    async def _expired_claim(self, client, db, seed):
        """An order whose claim expired unanswered: CANCELLED, refund owed."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place(client, seed)
        await _claim(client, seed, order["id"])
        await db.execute(text("""
            UPDATE customer_orders
               SET acceptance_deadline_at = now() - interval '5 minutes'
             WHERE id = :i"""), {"i": str(order["id"])})
        await db.commit()
        await AcceptanceService.process_acceptance_deadlines(
            db, outlet_id=uuid.UUID(seed["outlet_id"]))
        row = await _row(db, order["id"])
        assert row.status == "CANCELLED", f"precondition: {row.status}"
        assert row.manual_refund_due is True, "precondition: refund owed"
        return order

    async def test_the_happy_path_clears_the_obligation_and_strikes(
            self, client, db, seed):
        order = await self._expired_claim(client, db, seed)
        before = await _strikes(db, seed["customer_id"])

        r = await client.post(
            f"{API}/pos/orders/{order['id']}/payment-not-received",
            headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["manual_refund_due"] is False
        assert body["already"] is False

        row = await _row(db, order["id"])
        assert row.manual_refund_due is False, \
            "the restaurant no longer owes a refund it never received"
        assert row.manual_refund_reason == "restaurant_reported_not_received"
        assert await _strikes(db, seed["customer_id"]) == before + 1
        # Still never the gateway queue.
        assert not await _in_refund_queue(client, seed, order["id"])

    async def test_a_second_call_does_not_double_strike(
            self, client, db, seed):
        """A double-tap on a tablet must not cost the customer two strikes —
        two is the limit, so a double-tap would ban them outright."""
        order = await self._expired_claim(client, db, seed)
        url = f"{API}/pos/orders/{order['id']}/payment-not-received"

        first = await client.post(url, headers=seed["owner_auth"])
        assert first.status_code == 200, first.text
        after_first = await _strikes(db, seed["customer_id"])

        second = await client.post(url, headers=seed["owner_auth"])
        assert second.status_code == 200, second.text
        assert second.json()["already"] is True
        assert second.json()["manual_refund_due"] is False
        assert await _strikes(db, seed["customer_id"]) == after_first, \
            "the second call must be a no-op on the strike count"

    async def test_another_outlet_cannot_report_it(self, client, db, seed):
        """Outlet-scoped: a 404, which is also what every other order route
        returns for a foreign id, so this leaks no existence."""
        order = await self._expired_claim(client, db, seed)
        other = await _second_outlet_with_upi(db, seed)

        r = await client.post(
            f"{API}/pos/orders/{order['id']}/payment-not-received",
            headers=other["auth"])
        assert r.status_code == 404, r.text

        row = await _row(db, order["id"])
        assert row.manual_refund_due is True, "still owed by the real outlet"

    async def test_a_waiter_cannot_report_it(self, client, db, seed):
        """The side effect is a penalty on a customer and the reversal of a
        refund — the same gate as the payment settings."""
        order = await self._expired_claim(client, db, seed)
        rid = await db.scalar(text("SELECT id FROM roles WHERE name='Waiter'"))
        if rid is None:
            rid = await db.scalar(text(
                "INSERT INTO roles (name, permissions, created_at) "
                "VALUES ('Waiter','{}'::jsonb, now()) RETURNING id"))
        tag = uuid.uuid4().hex[:8]
        uid = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO users (id, username, hashed_password, is_active,
                               outlet_id, created_at)
            VALUES (:i,:u,:h,true,:o, now())"""),
            {"i": str(uid), "u": f"w_{tag}", "o": seed["outlet_id"],
             "h": get_password_hash("correct-horse")})
        await db.execute(text(
            "INSERT INTO user_roles (user_id, role_id) VALUES (:u,:r)"),
            {"u": str(uid), "r": rid})
        await db.commit()

        r = await client.post(
            f"{API}/pos/orders/{order['id']}/payment-not-received",
            headers={"Authorization":
                     f"Bearer {create_access_token(subject=f'w_{tag}')}"})
        assert r.status_code == 403, r.text

    async def test_an_order_that_did_not_expire_is_refused(
            self, client, db, seed):
        """This route is ONLY for the expiry case. On a live order the
        restaurant has /reject; letting them strike a customer on an order
        they simply have not looked at yet would make the strike worthless."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place(client, seed)
        await _claim(client, seed, order["id"])
        before = await _strikes(db, seed["customer_id"])

        r = await client.post(
            f"{API}/pos/orders/{order['id']}/payment-not-received",
            headers=seed["owner_auth"])
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "NOT_AN_EXPIRED_CLAIM"
        assert await _strikes(db, seed["customer_id"]) == before

    async def test_an_accepted_order_is_refused(self, client, db, seed):
        """Accepting IS the confirmation that the money arrived. Reporting it
        missing afterwards would unwind a payment the restaurant recorded."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place(client, seed)
        await _claim(client, seed, order["id"])
        assert (await _accept(client, seed, order["id"])).status_code == 200

        r = await client.post(
            f"{API}/pos/orders/{order['id']}/payment-not-received",
            headers=seed["owner_auth"])
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_ALREADY_RECORDED"

    async def test_after_the_window_it_is_refused(self, client, db, seed):
        """A bounded window. Weeks later nobody can honestly remember whether
        one UPI credit among hundreds arrived, and a strike that lands a month
        after the order is indistinguishable from a grudge."""
        order = await self._expired_claim(client, db, seed)
        days = CarevoService.NOT_RECEIVED_WINDOW.days + 1
        # The window is measured off updated_at — the last time anybody
        # touched the order, which for a cancelled one is the cancellation.
        await db.execute(text("""
            UPDATE customer_orders
               SET updated_at = now() - (:d || ' days')::interval,
                   created_at = now() - (:d || ' days')::interval,
                   payment_claimed_at =
                       payment_claimed_at - (:d || ' days')::interval
             WHERE id = :i"""), {"d": str(days), "i": str(order["id"])})
        await db.commit()
        before = await _strikes(db, seed["customer_id"])

        r = await client.post(
            f"{API}/pos/orders/{order['id']}/payment-not-received",
            headers=seed["owner_auth"])
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "REPORT_WINDOW_EXPIRED"
        assert await _strikes(db, seed["customer_id"]) == before

    async def test_two_reports_reach_the_limit_and_upi_disappears(
            self, client, db, seed):
        """The point of the strike. At FALSE_CLAIM_STRIKE_LIMIT the customer
        can no longer choose direct UPI anywhere — the only lever a restaurant
        has against somebody who taps "I've paid" without paying."""
        assert FALSE_CLAIM_STRIKE_LIMIT == 2, \
            "this test walks the limit explicitly"
        await db.execute(text(
            "UPDATE customers SET false_claim_count = 0 WHERE id = :i"),
            {"i": seed["customer_id"]})
        await db.commit()

        for n in (1, 2):
            order = await self._expired_claim(client, db, seed)
            r = await client.post(
                f"{API}/pos/orders/{order['id']}/payment-not-received",
                headers=seed["owner_auth"])
            assert r.status_code == 200, r.text
            assert await _strikes(db, seed["customer_id"]) == n

        # UPI_MANUAL is gone from what this customer is offered...
        r = await client.get(
            f"{API}/customer/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["customer_auth"])
        if r.status_code == 200:
            assert PAY_UPI_MANUAL not in (r.json().get("methods") or []), \
                "a struck customer must not be offered direct UPI"

        # ...and asking for it anyway is refused, which is the enforcement that
        # actually matters: a stale app build must not get through.
        bad = await client.post(f"{API}/customer/orders",
                                headers=seed["customer_auth"],
                                json={"outlet_id": seed["outlet_id"],
                                      "payment_method": PAY_UPI_MANUAL,
                                      "items": [{"menu_item_id":
                                                 seed["menu_item_id"],
                                                 "quantity": 1}]})
        assert bad.status_code in (403, 409, 422), bad.text


# ============ FINDING 4: a partial PATCH must not erase saved fields ========

class TestPartialPatchDoesNotEraseSavedFields:
    async def test_toggles_only_leaves_the_upi_details_intact(
            self, client, db, seed):
        """THE REPRO. The owner has direct UPI configured and turns
        pay-at-pickup on. The body carries only the three toggles — which is
        what the screen sends — and the VPA must survive it."""
        await _enable_upi(db, seed["outlet_id"])
        before = await _outlet_payment_row(db, seed["outlet_id"])
        assert before.upi_vpa == VPA, "precondition: a VPA is saved"
        assert before.upi_attested_at is not None

        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json={"prepaid": False,
                                     "pay_at_pickup": True,
                                     "upi_manual": True})
        assert r.status_code == 200, r.text

        after = await _outlet_payment_row(db, seed["outlet_id"])
        assert after.upi_vpa == VPA, "the payee VPA was erased"
        assert after.upi_payee_name == PAYEE
        assert after.upi_attested_at == before.upi_attested_at, \
            "the attestation timestamp must not be re-stamped either"
        assert after.payment_pay_at_pickup_enabled is True, \
            "and the edit the owner actually made did land"
        # The resolved list still offers UPI, which it could not if the VPA
        # had gone (ck_outlets_upi_manual_requires_vpa would have blocked it).
        assert PAY_UPI_MANUAL in r.json()["effective_methods"]

    async def test_an_explicit_null_is_refused_not_obeyed(
            self, client, db, seed):
        """"Absent" and "null" must not mean the same thing. Absent keeps the
        value; null is a request to clear the only field that makes direct UPI
        work, so it is a 422 rather than a silent outage."""
        await _enable_upi(db, seed["outlet_id"])
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json={"prepaid": False, "pay_at_pickup": True,
                                     "upi_manual": True, "upi_vpa": None})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "UPI_ID_CANNOT_BE_CLEARED"
        assert (await _outlet_payment_row(db, seed["outlet_id"])).upi_vpa == VPA

    async def test_a_real_change_still_goes_through(self, client, db, seed):
        """The control: keeping absent fields must not freeze present ones."""
        await _enable_upi(db, seed["outlet_id"])
        new_vpa = "testrestaurant2@okhdfcbank"
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json={"prepaid": False, "pay_at_pickup": False,
                                     "upi_manual": True,
                                     "upi_vpa": new_vpa,
                                     "upi_payee_name": "Renamed Kitchen",
                                     "upi_attested": True})
        assert r.status_code == 200, r.text
        after = await _outlet_payment_row(db, seed["outlet_id"])
        assert after.upi_vpa == new_vpa
        assert after.upi_payee_name == "Renamed Kitchen"


# ============ FINDING 5a: accept is one transaction ========================

class TestAcceptIsAtomic:
    async def test_payment_and_pickup_code_land_together(
            self, client, db, seed):
        """Accept records the payment AND assigns the pickup code, in ONE
        transaction. The code-allocation path used to run a stale-order sweep
        that COMMITS, so a failure anywhere after it left the payment recorded
        and no code to collect against — money taken, nothing to hand over.

        The fix passes sweep=False on the accept path, so the two assertions
        here are: the pair lands together, and the stale row is left ALONE
        (proving no commit happened part-way through). The sweep still runs on
        every other read, which is where it belongs.
        """
        await _enable_upi(db, seed["outlet_id"])

        # A stale pickup row at the same outlet, so the sweep is not a no-op.
        stale = await _place(client, seed)
        await _claim(client, seed, stale["id"])
        assert (await _accept(client, seed, stale["id"])).status_code == 200
        await db.execute(text("""
            UPDATE customer_orders
               SET updated_at = now() - (:m || ' minutes')::interval,
                   accepted_at = now() - (:m || ' minutes')::interval,
                   created_at = now() - (:m || ' minutes')::interval,
                   release_at = NULL
             WHERE id = :i"""),
            {"m": str(settings.PICKUP_TTL_MINUTES + 240),
             "i": str(stale["id"])})
        await db.commit()

        order = await _place(client, seed)
        await _claim(client, seed, order["id"])
        r = await _accept(client, seed, order["id"])
        assert r.status_code == 200, r.text

        row = await _row(db, order["id"])
        both = (row.payment_status == "PAID", row.pickup_code is not None)
        assert both[0] == both[1], (
            "payment and pickup code must be all-or-nothing, got "
            f"payment_status={row.payment_status!r} "
            f"pickup_code={row.pickup_code!r}")
        assert all(both), "and on the happy path both are present"

        # And the stale row is untouched: accept no longer commits a sweep
        # part-way through its own transaction.
        assert (await _row(db, stale["id"])).status == "RECEIVED",             "accept must not run a committing sweep inside its transaction"


# ============ FINDING 5b: an empty method list is never reachable ===========

class TestNoEffectivePaymentMethod:
    """An outlet whose RESOLVED method list is empty takes no orders at all,
    while every flag on the row looks individually fine and the CHECK
    constraint passes. The shape: prepaid on, pickup off, UPI off, and
    cashfree_unlocked false — the lock withdraws the only method.

    WHICH ROUTE CAN REACH IT. Not the owner route: a pre-existing guard there
    answers 409 CASHFREE_LOCKED to any body that asks for prepaid on a locked
    outlet, which closes this shape as a side effect, and the first two tests
    pin that so a later edit cannot quietly remove it. The ADMIN route is the
    reachable one — it is also the only route that can SET the lock, so it can
    both pick prepaid-only and revoke the gateway under it. That is where the
    floor was missing and where it was added.
    """

    async def test_the_owner_route_refuses_prepaid_while_locked(
            self, client, db, seed):
        """Closed by CASHFREE_LOCKED. Pinned because it is load-bearing: this
        refusal is what keeps the empty shape off the owner route."""
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()

        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json={"prepaid": True, "pay_at_pickup": False,
                                     "upi_manual": False})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "CASHFREE_LOCKED"

    async def test_the_owner_route_refuses_all_three_off(self, client, seed):
        """The other half of the same floor, from the opposite direction."""
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json={"prepaid": False, "pay_at_pickup": False,
                                     "upi_manual": False})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "NO_PAYMENT_METHOD"

    async def test_the_admin_route_refuses_prepaid_only_while_locked(
            self, client, db, seed):
        """THE REPRO, on the route that can reach it."""
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()

        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "NO_EFFECTIVE_PAYMENT_METHOD"

    async def test_the_admin_route_refuses_revoking_the_last_method(
            self, client, db, seed):
        """THE SECOND REPRO, and the worse one: the outlet is already trading
        on prepaid, and the admin revokes the gateway. Nothing about the
        payment flags changes, so no flag-level rule can catch it — the list
        simply becomes empty under a working restaurant."""
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False,
                  "upi_manual": False})
        assert r.status_code == 200, r.text
        assert r.json()["effective_methods"] == [PAY_PREPAID]

        revoke = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False,
                  "cashfree_unlocked": False})
        assert revoke.status_code == 422, revoke.text
        assert revoke.json()["detail"]["error"] == "NO_EFFECTIVE_PAYMENT_METHOD"

        # And the outlet is still trading — the refusal did not half-apply.
        row = await _outlet_payment_row(db, seed["outlet_id"])
        assert row.cashfree_unlocked is True
        still = await client.get(SETTINGS, headers=seed["owner_auth"])
        assert still.json()["effective_methods"] == [PAY_PREPAID],             "the refusal must not have half-applied"

    async def test_revoking_is_fine_when_another_method_remains(
            self, client, db, seed):
        """The control. Revoking the gateway is a legitimate admin act — the
        floor is about the list going EMPTY, not about the lock itself."""
        await _enable_upi(db, seed["outlet_id"], prepaid=True)

        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False,
                  "upi_manual": True, "cashfree_unlocked": False})
        assert r.status_code == 200, r.text
        assert r.json()["effective_methods"] == [PAY_UPI_MANUAL]

    async def test_unlocked_prepaid_only_is_fine(self, client, seed):
        """And prepaid-only is a perfectly ordinary configuration unlocked."""
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json={"prepaid": True, "pay_at_pickup": False,
                                     "upi_manual": False})
        assert r.status_code == 200, r.text
        assert r.json()["effective_methods"] == [PAY_PREPAID]

    async def test_upi_is_the_owners_way_out_of_the_lock(
            self, client, db, seed):
        """The whole reason direct UPI exists: trade without waiting for
        CareVo to activate the gateway. prepaid stays off because the owner
        route will not let them ask for a method they do not have."""
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()

        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json={"prepaid": False, "pay_at_pickup": False,
                                     "upi_manual": True, "upi_vpa": VPA,
                                     "upi_payee_name": PAYEE,
                                     "upi_attested": True})
        assert r.status_code == 200, r.text
        assert r.json()["effective_methods"] == [PAY_UPI_MANUAL]


# ============ FINDING 5c: a customer's own read releases their cap ==========

class TestTheCustomerCanRecoverTheirOwnCap:
    async def test_an_abandoned_order_elsewhere_does_not_lock_them_out(
            self, client, db, seed):
        """THE REPRO. A customer starts a direct-UPI order at outlet A and
        never pays. The sweep that releases it ran only when A's STAFF polled,
        so if A has closed for the night the order stays open forever and the
        global one-open-order cap locks the customer out of ordering anywhere.

        Nobody at either outlet polls anything in this test — that is the point.
        """
        await _enable_upi(db, seed["outlet_id"])
        abandoned = await _place(client, seed)
        await _age_claim(db, abandoned["id"], minutes=120)
        await db.execute(text("""
            UPDATE customer_orders
               SET payment_claimed_at = NULL,
                   created_at = now() - interval '120 minutes'
             WHERE id = :i"""), {"i": str(abandoned["id"])})
        await db.commit()

        other = await _second_outlet_with_upi(db, seed)
        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"],
                              json={"outlet_id": other["outlet_id"],
                                    "payment_method": PAY_UPI_MANUAL,
                                    "items": [{"menu_item_id":
                                               other["menu_item_id"],
                                               "quantity": 1}]})
        assert r.status_code == 200, r.text

        assert (await _row(db, abandoned["id"])).status != "CREATED", \
            "the abandoned order should have been swept to a terminal status"

    async def test_reading_their_own_order_runs_the_sweep(
            self, client, db, seed):
        """The customer's own GET is a second trigger, so an app that polls its
        order screen recovers without placing anything."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place(client, seed)
        await db.execute(text("""
            UPDATE customer_orders SET created_at = now() - interval '120 min'
             WHERE id = :i"""), {"i": str(order["id"])})
        await db.commit()

        r = await client.get(f"{API}/customer/orders/{order['id']}",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        assert (await _row(db, order["id"])).status != "CREATED"

    async def test_a_live_order_is_not_swept(self, client, db, seed):
        """The control. The sweep must only take orders past the window, or a
        customer loses the order they are mid-payment on."""
        await _enable_upi(db, seed["outlet_id"])
        order = await _place(client, seed)
        r = await client.get(f"{API}/customer/orders/{order['id']}",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        assert (await _row(db, order["id"])).status == "CREATED"
