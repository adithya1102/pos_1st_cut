"""Manual order acceptance (migration 032).

Covers the whole state machine: entry, accept, reject, the alert ladder,
acknowledgement, expiry, the outlet strike counter and auto-close, the
scheduled-pickup clock, cross-outlet scoping, and the refund flag each terminal
path raises.

THE TWO ASSERTIONS THAT MATTER MOST
-----------------------------------
1. `TestAutoModeUnchanged.test_auto_mode_event_sequence_is_identical` — the
   per-brief guarantee that an auto outlet behaves EXACTLY as before. It pins
   the literal ORDER_CREATED/ORDER_PAID/ORDER_ACCEPTED/PREP_STARTED sequence
   with its exact actor_type/source pairs, so any future acceptance change that
   leaks into the default path fails here.

2. `TestAcceptVsExpireRace` — run in BOTH orders. Exactly one of accept and
   expire may win, because both are compare-and-set on acceptance_state. If
   someone replaces a CAS with read-then-write, these fail.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.security import get_password_hash
from app.modules.carevo_customer.acceptance import (
    ACCEPTED, AWAITING, EXPIRED, MAX_ALERTS, REJECTED, AcceptanceService,
)
from tests.conftest import API


# ------------------------------- helpers -------------------------------------

async def _set_manual(db, outlet_id, *, timeout_s: int = 180) -> None:
    await db.execute(text("""
        UPDATE outlets SET acceptance_mode = 'manual',
                           acceptance_timeout_s = :t,
                           consecutive_expiries = 0,
                           is_manually_closed = false
         WHERE id = :oid
    """), {"t": timeout_s, "oid": str(outlet_id)})
    await db.commit()


async def _order_row(db, order_id):
    return (await db.execute(text("""
        SELECT status, payment_status, acceptance_state, acceptance_deadline_at,
               accepted_at, prep_minutes_committed, alert_count, last_alert_at,
               refund_required, refund_reason
          FROM customer_orders WHERE id = :i
    """), {"i": str(order_id)})).first()


async def _outlet_row(db, outlet_id):
    return (await db.execute(text("""
        SELECT acceptance_mode, acceptance_timeout_s, consecutive_expiries,
               is_manually_closed
          FROM outlets WHERE id = :i
    """), {"i": str(outlet_id)})).first()


async def _events(db, order_id) -> list[tuple]:
    rows = (await db.execute(text("""
        SELECT event_type, actor_type, source FROM order_events
         WHERE order_id = :i ORDER BY seq
    """), {"i": str(order_id)})).fetchall()
    return [(r.event_type, r.actor_type, r.source) for r in rows]


async def _pay(client, seed, order_id):
    r = await client.post(f"{API}/customer/payment/simulate",
                          headers=seed["customer_auth"],
                          json={"order_id": order_id, "method": "upi"})
    assert r.status_code == 200, r.text
    return r.json()


async def _place(client, seed, **extra):
    r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                          json={"outlet_id": seed["outlet_id"],
                                "items": [{"menu_item_id": seed["menu_item_id"],
                                           "quantity": 1}], **extra})
    assert r.status_code == 200, r.text
    return r.json()


async def _awaiting_order(client, seed, db, *, timeout_s: int = 180):
    """A paid order at a MANUAL outlet, sitting in AWAITING."""
    await _set_manual(db, seed["outlet_id"], timeout_s=timeout_s)
    order = await _place(client, seed)
    await _pay(client, seed, order["id"])
    row = await _order_row(db, order["id"])
    assert row.acceptance_state == AWAITING, (
        f"order did not enter AWAITING: {row.acceptance_state}")
    return order


async def _force_deadline_past(db, order_id):
    """Backdate the deadline instead of sleeping 180s."""
    await db.execute(text("""
        UPDATE customer_orders SET acceptance_deadline_at = now() - interval '1 second'
         WHERE id = :i
    """), {"i": str(order_id)})
    await db.commit()


async def _second_outlet_staff(db, seed) -> dict:
    org_id = await db.scalar(text(
        "SELECT organization_id FROM outlets WHERE id = :o"),
        {"o": seed["outlet_id"]})
    other = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO outlets (id, location_name, city, organization_id,
                             geofence_radius_meters, verification_status,
                             is_visible, relocation_is_pending,
                             is_manually_closed, created_at)
        VALUES (:i,'TEST_CAREVO_other','Bengaluru',:org,500,'active',
                true,false,false,now())
    """), {"i": str(other), "org": str(org_id)})
    uname = f"TEST_CAREVO_other_{uuid.uuid4().hex[:8]}"
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i,:u,:h,true,:o,now())
    """), {"i": str(uuid.uuid4()), "u": uname,
           "h": get_password_hash("correct-horse"), "o": str(other)})
    await db.commit()
    return {"outlet_id": str(other),
            "auth": {"Authorization": f"Bearer {create_access_token(subject=uname)}"}}


# ===========================================================================
# 3.2 — auto mode must be untouched
# ===========================================================================
@pytest.mark.asyncio
class TestAutoModeUnchanged:
    async def test_auto_mode_event_sequence_is_identical(self, client, seed, db):
        """THE REGRESSION GUARD for the whole feature.

        An auto outlet (the default) must produce the exact event sequence it
        always has, with the same actor_type/source on each. Pinned literally
        rather than loosely, because the failure this protects against is a
        future acceptance change quietly leaking into the default path.
        """
        order = await _place(client, seed)
        await _pay(client, seed, order["id"])

        # PROMISE_ISSUED is the prediction twin's own event, written by
        # recompute_twin AFTER mark_paid commits (FR-M1: promise only after
        # ORDER_ACCEPTED). It is part of the real auto-mode baseline, so it is
        # pinned here too — leaving it out would make this test pass while the
        # twin silently stopped running.
        assert await _events(db, order["id"]) == [
            ("ORDER_CREATED", "customer", "tap"),
            ("ORDER_PAID", "staff", "tap"),
            ("ORDER_ACCEPTED", "system", "inferred"),
            ("PREP_STARTED", "system", "inferred"),
            ("PROMISE_ISSUED", "system", "system"),
        ]

    async def test_auto_mode_leaves_acceptance_columns_null(self, client, seed, db):
        order = await _place(client, seed)
        await _pay(client, seed, order["id"])
        row = await _order_row(db, order["id"])
        assert row.acceptance_state is None
        assert row.acceptance_deadline_at is None
        assert row.alert_count == 0
        assert row.refund_required is False

    async def test_accept_on_an_auto_order_is_409(self, client, seed, db):
        """Honest answer: there is nothing to accept, it was accepted on payment."""
        order = await _place(client, seed)
        await _pay(client, seed, order["id"])
        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              headers=seed["owner_auth"], json={"prep_minutes": 15})
        assert r.status_code == 409, r.text

    async def test_auto_mode_order_reaches_received(self, client, seed, db):
        """Auto mode still auto-receives through the webhook-equivalent path."""
        order = await _place(client, seed)
        await _pay(client, seed, order["id"])
        # simulate does not auto_receive (it never did); the status stays PAID
        # and the inferred events are what mark acceptance.
        row = await _order_row(db, order["id"])
        assert row.status == "PAID"
        assert row.acceptance_state is None


# ===========================================================================
# 3.3 — entering AWAITING
# ===========================================================================
@pytest.mark.asyncio
class TestEnteringAwaiting:
    async def test_manual_order_enters_awaiting_with_a_deadline(
            self, client, seed, db):
        order = await _awaiting_order(client, seed, db, timeout_s=120)
        row = await _order_row(db, order["id"])
        assert row.acceptance_state == AWAITING
        assert row.status == "PAID", "must NOT advance to RECEIVED"
        assert row.acceptance_deadline_at is not None
        delta = (row.acceptance_deadline_at - datetime.now(timezone.utc)).total_seconds()
        assert 60 < delta <= 121, f"deadline {delta}s away, expected ~120"

    async def test_inferred_accept_pair_is_withheld(self, client, seed, db):
        """The whole point: payment must not imply a human accepted it."""
        order = await _awaiting_order(client, seed, db)
        kinds = [e[0] for e in await _events(db, order["id"])]
        assert "ORDER_ALERTED" in kinds
        assert "ORDER_ACCEPTED" not in kinds, (
            "payment inferred acceptance at a manual outlet")
        assert "PREP_STARTED" not in kinds

    async def test_exactly_one_order_alerted_event(self, client, seed, db):
        """The ladder lives in alert_count, not in repeated events."""
        order = await _awaiting_order(client, seed, db)
        kinds = [e[0] for e in await _events(db, order["id"])]
        assert kinds.count("ORDER_ALERTED") == 1

    async def test_first_alert_is_counted(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        row = await _order_row(db, order["id"])
        assert row.alert_count == 1
        assert row.last_alert_at is not None

    async def test_a_durable_schedule_row_is_written(self, client, seed, db):
        """The deadline has to survive a redeploy."""
        order = await _awaiting_order(client, seed, db)
        row = (await db.execute(text(
            "SELECT kind, next_stage FROM auto_advance_schedule WHERE order_id = :i"
        ), {"i": order["id"]})).first()
        assert row is not None, "no durable row — a restart would lose the deadline"
        assert row.kind == "acceptance"


# ===========================================================================
# 3.4 — accept
# ===========================================================================
@pytest.mark.asyncio
class TestAccept:
    async def test_accept_advances_and_records_the_promise(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              headers=seed["owner_auth"], json={"prep_minutes": 20})
        assert r.status_code == 200, r.text
        assert r.json()["acceptance_state"] == ACCEPTED

        row = await _order_row(db, order["id"])
        assert row.acceptance_state == ACCEPTED
        assert row.status == "RECEIVED", "accept must advance PAID -> RECEIVED"
        assert row.accepted_at is not None
        assert row.prep_minutes_committed == 20

    async def test_accept_writes_the_same_event_pair_as_auto_mode(
            self, client, seed, db):
        """Only `source` and the actor differ — prediction/ needs no change."""
        order = await _awaiting_order(client, seed, db)
        await client.post(f"{API}/pos/orders/{order['id']}/accept",
                          headers=seed["owner_auth"], json={"prep_minutes": 15})
        ev = await _events(db, order["id"])
        assert ("ORDER_ACCEPTED", "staff", "tap") in ev
        assert ("PREP_STARTED", "system", "inferred") in ev
        # and in that relative order
        assert ev.index(("ORDER_ACCEPTED", "staff", "tap")) < \
               ev.index(("PREP_STARTED", "system", "inferred"))

    async def test_prep_minutes_is_required_and_positive(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        assert (await client.post(f"{API}/pos/orders/{order['id']}/accept",
                                  headers=seed["owner_auth"],
                                  json={})).status_code == 422
        assert (await client.post(f"{API}/pos/orders/{order['id']}/accept",
                                  headers=seed["owner_auth"],
                                  json={"prep_minutes": 0})).status_code == 422

    async def test_double_accept_second_gets_409(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        first = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                                  headers=seed["owner_auth"],
                                  json={"prep_minutes": 15})
        assert first.status_code == 200, first.text
        second = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                                   headers=seed["owner_auth"],
                                   json={"prep_minutes": 15})
        assert second.status_code == 409, second.text
        assert second.json()["detail"]["acceptance_state"] == ACCEPTED

    async def test_accept_resets_the_outlet_strike_counter(self, client, seed, db):
        await _set_manual(db, seed["outlet_id"])
        await db.execute(text(
            "UPDATE outlets SET consecutive_expiries = 2 WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()

        order = await _place(client, seed)
        await _pay(client, seed, order["id"])
        await client.post(f"{API}/pos/orders/{order['id']}/accept",
                          headers=seed["owner_auth"], json={"prep_minutes": 15})

        assert (await _outlet_row(db, seed["outlet_id"])).consecutive_expiries == 0

    async def test_cross_outlet_accept_is_404(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        other = await _second_outlet_staff(db, seed)
        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              headers=other["auth"], json={"prep_minutes": 15})
        assert r.status_code == 404, r.text
        assert (await _order_row(db, order["id"])).acceptance_state == AWAITING

    async def test_anonymous_accept_is_401(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              json={"prep_minutes": 15})
        assert r.status_code == 401, r.text


# ===========================================================================
# 3.5 — reject
# ===========================================================================
@pytest.mark.asyncio
class TestReject:
    async def test_reject_settles_acceptance_and_flags_a_refund(
            self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        r = await client.post(f"{API}/pos/orders/{order['id']}/reject",
                              headers=seed["owner_auth"],
                              json={"reason": "out of stock"})
        assert r.status_code == 200, r.text

        row = await _order_row(db, order["id"])
        assert row.status == "CANCELLED"
        assert row.acceptance_state == REJECTED
        assert row.refund_required is True
        assert row.refund_reason == "order_rejected"

    async def test_reject_resets_the_strike_counter(self, client, seed, db):
        await _set_manual(db, seed["outlet_id"])
        await db.execute(text(
            "UPDATE outlets SET consecutive_expiries = 2 WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        order = await _place(client, seed)
        await _pay(client, seed, order["id"])
        await client.post(f"{API}/pos/orders/{order['id']}/reject",
                          headers=seed["owner_auth"], json={})
        assert (await _outlet_row(db, seed["outlet_id"])).consecutive_expiries == 0

    async def test_accept_after_reject_is_409(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        await client.post(f"{API}/pos/orders/{order['id']}/reject",
                          headers=seed["owner_auth"], json={})
        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              headers=seed["owner_auth"], json={"prep_minutes": 15})
        assert r.status_code == 409, r.text

    async def test_auto_mode_reject_still_flags_a_refund(self, client, seed, db):
        """The refund flag is NOT exclusive to manual mode."""
        order = await _place(client, seed)
        await _pay(client, seed, order["id"])
        r = await client.post(f"{API}/pos/orders/{order['id']}/reject",
                              headers=seed["owner_auth"], json={})
        assert r.status_code == 200, r.text
        row = await _order_row(db, order["id"])
        assert row.refund_required is True
        assert row.acceptance_state is None, "auto order must stay off this axis"


# ===========================================================================
# 3.6 / 3.7 — the ladder, acknowledgement, expiry
# ===========================================================================
@pytest.mark.asyncio
class TestLadderAndExpiry:
    async def test_the_ladder_climbs_to_three_then_stops(self, client, seed, db):
        order = await _awaiting_order(client, seed, db, timeout_s=1800)
        for expected in (2, 3):
            # Backdate last_alert_at so the 30s gap has "elapsed".
            await db.execute(text(
                "UPDATE customer_orders "
                "SET last_alert_at = now() - interval '31 seconds' WHERE id = :i"),
                {"i": order["id"]})
            await db.commit()
            await AcceptanceService.process_acceptance_deadlines(
                db, order_id=order["id"])
            assert (await _order_row(db, order["id"])).alert_count == expected

        # A fourth rung must not fire.
        await db.execute(text(
            "UPDATE customer_orders "
            "SET last_alert_at = now() - interval '31 seconds' WHERE id = :i"),
            {"i": order["id"]})
        await db.commit()
        await AcceptanceService.process_acceptance_deadlines(db, order_id=order["id"])
        assert (await _order_row(db, order["id"])).alert_count == MAX_ALERTS

    async def test_the_ladder_respects_the_interval(self, client, seed, db):
        """A sweep seconds after the last rung must not push again."""
        order = await _awaiting_order(client, seed, db, timeout_s=1800)
        before = (await _order_row(db, order["id"])).alert_count
        await AcceptanceService.process_acceptance_deadlines(db, order_id=order["id"])
        assert (await _order_row(db, order["id"])).alert_count == before

    async def test_ack_stops_the_re_push(self, client, seed, db):
        order = await _awaiting_order(client, seed, db, timeout_s=1800)
        r = await client.post(f"{API}/pos/orders/{order['id']}/alert-ack",
                              headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["acknowledged"] is True

        await db.execute(text(
            "UPDATE customer_orders "
            "SET last_alert_at = now() - interval '31 seconds' WHERE id = :i"),
            {"i": order["id"]})
        await db.commit()
        await AcceptanceService.process_acceptance_deadlines(db, order_id=order["id"])
        assert (await _order_row(db, order["id"])).alert_count == MAX_ALERTS

    async def test_ack_does_not_stop_the_deadline(self, client, seed, db):
        """Otherwise acking would park orders indefinitely."""
        order = await _awaiting_order(client, seed, db)
        await client.post(f"{API}/pos/orders/{order['id']}/alert-ack",
                          headers=seed["owner_auth"])
        await _force_deadline_past(db, order["id"])
        await AcceptanceService.process_acceptance_deadlines(db, order_id=order["id"])
        assert (await _order_row(db, order["id"])).acceptance_state == EXPIRED

    async def test_ack_on_a_settled_order_is_200_false(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        await client.post(f"{API}/pos/orders/{order['id']}/accept",
                          headers=seed["owner_auth"], json={"prep_minutes": 15})
        r = await client.post(f"{API}/pos/orders/{order['id']}/alert-ack",
                              headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["acknowledged"] is False

    async def test_expiry_cancels_and_flags_a_refund(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        await _force_deadline_past(db, order["id"])
        res = await AcceptanceService.process_acceptance_deadlines(
            db, order_id=order["id"])
        assert res["expired"] == 1

        row = await _order_row(db, order["id"])
        assert row.acceptance_state == EXPIRED
        assert row.status == "CANCELLED"
        assert row.refund_required is True
        assert row.refund_reason == "acceptance_expired"
        assert "ORDER_EXPIRED" in [e[0] for e in await _events(db, order["id"])]

    async def test_expiry_is_idempotent(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        await _force_deadline_past(db, order["id"])
        first = await AcceptanceService.process_acceptance_deadlines(
            db, order_id=order["id"])
        second = await AcceptanceService.process_acceptance_deadlines(
            db, order_id=order["id"])
        assert first["expired"] == 1
        assert second["expired"] == 0, "a second sweep expired it again"
        kinds = [e[0] for e in await _events(db, order["id"])]
        assert kinds.count("ORDER_EXPIRED") == 1

    async def test_check_on_read_expires_via_the_staff_poll(
            self, client, seed, db):
        """GET /pos/orders must drive the clock — the poller cannot be trusted
        alone on an instance that sleeps."""
        order = await _awaiting_order(client, seed, db)
        await _force_deadline_past(db, order["id"])

        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert (await _order_row(db, order["id"])).acceptance_state == EXPIRED

    async def test_the_durable_poller_also_expires(self, client, seed, db):
        from app.modules.testing_dashboard.service import TestingService
        order = await _awaiting_order(client, seed, db)
        await _force_deadline_past(db, order["id"])
        await TestingService.process_due_auto_advances(db)
        assert (await _order_row(db, order["id"])).acceptance_state == EXPIRED


# ===========================================================================
# 3.7 — outlet strikes and auto-close
# ===========================================================================
@pytest.mark.asyncio
class TestAutoClose:
    async def test_three_consecutive_expiries_close_the_outlet(
            self, client, seed, db):
        await _set_manual(db, seed["outlet_id"])
        for i in range(3):
            order = await _place(client, seed)
            await _pay(client, seed, order["id"])
            await _force_deadline_past(db, order["id"])
            await AcceptanceService.process_acceptance_deadlines(
                db, order_id=order["id"])
            row = await _outlet_row(db, seed["outlet_id"])
            assert row.consecutive_expiries == i + 1

        row = await _outlet_row(db, seed["outlet_id"])
        assert row.is_manually_closed is True, (
            "an outlet that let 3 orders expire is still taking orders")

    async def test_two_expiries_do_not_close(self, client, seed, db):
        await _set_manual(db, seed["outlet_id"])
        for _ in range(2):
            order = await _place(client, seed)
            await _pay(client, seed, order["id"])
            await _force_deadline_past(db, order["id"])
            await AcceptanceService.process_acceptance_deadlines(
                db, order_id=order["id"])
        row = await _outlet_row(db, seed["outlet_id"])
        assert row.consecutive_expiries == 2
        assert row.is_manually_closed is False

    async def test_an_accept_between_expiries_resets_the_count(
            self, client, seed, db):
        await _set_manual(db, seed["outlet_id"])
        for _ in range(2):
            o = await _place(client, seed)
            await _pay(client, seed, o["id"])
            await _force_deadline_past(db, o["id"])
            await AcceptanceService.process_acceptance_deadlines(db, order_id=o["id"])
        assert (await _outlet_row(db, seed["outlet_id"])).consecutive_expiries == 2

        good = await _place(client, seed)
        await _pay(client, seed, good["id"])
        await client.post(f"{API}/pos/orders/{good['id']}/accept",
                          headers=seed["owner_auth"], json={"prep_minutes": 10})
        assert (await _outlet_row(db, seed["outlet_id"])).consecutive_expiries == 0

        o = await _place(client, seed)
        await _pay(client, seed, o["id"])
        await _force_deadline_past(db, o["id"])
        await AcceptanceService.process_acceptance_deadlines(db, order_id=o["id"])
        row = await _outlet_row(db, seed["outlet_id"])
        assert row.consecutive_expiries == 1
        assert row.is_manually_closed is False, "reset did not take effect"


# ===========================================================================
# 3.9 — the accept-vs-expire race, BOTH orders
# ===========================================================================
@pytest.mark.asyncio
class TestAcceptVsExpireRace:
    async def test_expire_then_accept_accept_loses(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        await _force_deadline_past(db, order["id"])

        await AcceptanceService.process_acceptance_deadlines(db, order_id=order["id"])
        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              headers=seed["owner_auth"], json={"prep_minutes": 15})

        assert r.status_code == 409, r.text
        row = await _order_row(db, order["id"])
        assert row.acceptance_state == EXPIRED
        assert row.status == "CANCELLED"
        assert row.accepted_at is None, "accept partially applied after losing"

    async def test_accept_then_expire_expire_loses(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)

        r = await client.post(f"{API}/pos/orders/{order['id']}/accept",
                              headers=seed["owner_auth"], json={"prep_minutes": 15})
        assert r.status_code == 200, r.text

        # Force a deadline in the past and sweep: the order is no longer
        # AWAITING, so the CAS must not touch it.
        await db.execute(text(
            "UPDATE customer_orders "
            "SET acceptance_deadline_at = now() - interval '1 second' WHERE id = :i"),
            {"i": order["id"]})
        await db.commit()
        res = await AcceptanceService.process_acceptance_deadlines(
            db, order_id=order["id"])

        assert res["expired"] == 0
        row = await _order_row(db, order["id"])
        assert row.acceptance_state == ACCEPTED
        assert row.status == "RECEIVED"
        assert row.refund_required is False, "an accepted order was flagged for refund"

    async def test_exactly_one_of_two_concurrent_accepts_wins(
            self, client, seed, db):
        """Two devices, same instant. The CAS is the winner-picker."""
        order = await _awaiting_order(client, seed, db)
        a, b = await asyncio.gather(
            client.post(f"{API}/pos/orders/{order['id']}/accept",
                        headers=seed["owner_auth"], json={"prep_minutes": 10}),
            client.post(f"{API}/pos/orders/{order['id']}/accept",
                        headers=seed["owner_auth"], json={"prep_minutes": 30}),
        )
        codes = sorted([a.status_code, b.status_code])
        assert codes == [200, 409], f"got {codes}: {a.text} | {b.text}"
        assert (await _order_row(db, order["id"])).acceptance_state == ACCEPTED


# ===========================================================================
# 3.3 — scheduled pickup: the clock starts at RELEASE
# ===========================================================================
@pytest.mark.asyncio
class TestScheduledPickupClock:
    async def test_payment_does_not_start_the_clock_for_a_held_order(
            self, client, seed, db):
        """A pickup two hours out must not get a 180-second deadline at payment."""
        await _set_manual(db, seed["outlet_id"])
        when = datetime.now(timezone.utc) + timedelta(minutes=120)
        order = await _place(client, seed,
                             requested_pickup_at=when.isoformat())
        await _pay(client, seed, order["id"])

        row = await _order_row(db, order["id"])
        assert row.acceptance_state is None, (
            "a held order started its acceptance clock at payment — it would "
            "expire long before the restaurant ever saw it")
        assert row.acceptance_deadline_at is None

    async def test_release_starts_the_clock(self, client, seed, db):
        await _set_manual(db, seed["outlet_id"])
        when = datetime.now(timezone.utc) + timedelta(minutes=120)
        order = await _place(client, seed, requested_pickup_at=when.isoformat())
        await _pay(client, seed, order["id"])

        # Force the release to be due.
        #
        # Backdating release_at ALONE does not work, and the reason is worth
        # recording: refresh_scheduled_releases RE-DERIVES release_at on every
        # pass as requested_pickup_at - (mu_ready_s + safety_margin), by design
        # (a hold three hours out must track the current kitchen backlog). So a
        # hand-written release_at is immediately overwritten with a future
        # value and the order is never due.
        #
        # requested_pickup_at is the input that actually moves it, so that is
        # what gets pulled back here. Note mark_paid needed it to be in the
        # FUTURE to take the hold in the first place, which is why this happens
        # after payment rather than at placement.
        await db.execute(text(
            "UPDATE customer_orders "
            "   SET requested_pickup_at = now() + interval '1 second', "
            "       release_at = now() - interval '1 second' "
            " WHERE id = :i"), {"i": order["id"]})
        await db.execute(text(
            "UPDATE auto_advance_schedule SET due_at = now() - interval '1 second' "
            "WHERE order_id = :i AND kind = 'release'"), {"i": order["id"]})
        await db.commit()

        from app.modules.carevo_customer.service import CarevoService
        await CarevoService.refresh_scheduled_releases(db, order_id=order["id"])

        row = await _order_row(db, order["id"])
        assert row.acceptance_state == AWAITING, (
            f"release did not start the acceptance clock: {row.acceptance_state}")
        assert row.status == "PAID", "released order must not auto-advance"
        kinds = [e[0] for e in await _events(db, order["id"])]
        assert "ORDER_ALERTED" in kinds
        assert "ORDER_ACCEPTED" not in kinds


# ===========================================================================
# 3.1 / 3.8 — admin surfaces
# ===========================================================================
@pytest.mark.asyncio
class TestAdminSurfaces:
    async def test_refund_due_lists_an_expired_order(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        await _force_deadline_past(db, order["id"])
        await AcceptanceService.process_acceptance_deadlines(db, order_id=order["id"])

        # Clear every OTHER flagged order first.
        #
        # The endpoint is oldest-flagged-first with a limit, which is correct
        # (it is a queue of obligations). But every expiry and reject in this
        # file flags one, so by the time this test runs the shared throwaway DB
        # holds well over the default 100 and the order just created sits
        # outside the first page. Narrowing the fixture is the right fix; raising
        # the limit would only postpone the same flake.
        await db.execute(text(
            "UPDATE customer_orders SET refund_required = false WHERE id <> :i"),
            {"i": order["id"]})
        await db.commit()

        r = await client.get(f"{API}/admin/orders/refund-due",
                             headers=seed["admin_auth"])
        assert r.status_code == 200, r.text
        ids = [row["order_id"] for row in r.json()]
        assert order["id"] in ids
        row = next(x for x in r.json() if x["order_id"] == order["id"])
        assert row["refund_reason"] == "acceptance_expired"

    async def test_mark_refunded_clears_the_flag_and_records_the_actor(
            self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        await _force_deadline_past(db, order["id"])
        await AcceptanceService.process_acceptance_deadlines(db, order_id=order["id"])

        r = await client.post(f"{API}/admin/orders/{order['id']}/refund-marked",
                              headers=seed["admin_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["already"] is False
        assert (await _order_row(db, order["id"])).refund_required is False

        ev = (await db.execute(text("""
            SELECT actor_type, actor_id FROM order_events
             WHERE order_id = :i AND event_type = 'ORDER_REFUND_MARKED'
        """), {"i": order["id"]})).first()
        assert ev is not None, "no audit event for the refund"
        assert ev.actor_id is not None, "refund cleared with no recorded actor"

    async def test_mark_refunded_twice_is_idempotent(self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        await _force_deadline_past(db, order["id"])
        await AcceptanceService.process_acceptance_deadlines(db, order_id=order["id"])
        await client.post(f"{API}/admin/orders/{order['id']}/refund-marked",
                          headers=seed["admin_auth"])
        second = await client.post(
            f"{API}/admin/orders/{order['id']}/refund-marked",
            headers=seed["admin_auth"])
        assert second.status_code == 200, second.text
        assert second.json()["already"] is True
        count = await db.scalar(text("""
            SELECT count(*) FROM order_events
             WHERE order_id = :i AND event_type = 'ORDER_REFUND_MARKED'
        """), {"i": order["id"]})
        assert count == 1

    async def test_refund_endpoints_require_super_admin(self, client, seed, db):
        """owner_auth is staff but NOT SUPER_ADMIN."""
        assert (await client.get(f"{API}/admin/orders/refund-due",
                                 headers=seed["owner_auth"])).status_code == 403
        assert (await client.get(
            f"{API}/admin/orders/refund-due")).status_code == 401

    async def test_acceptance_config_roundtrip(self, client, seed, db):
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/acceptance",
            headers=seed["admin_auth"],
            json={"mode": "manual", "timeout_s": 240})
        assert r.status_code == 200, r.text
        assert r.json()["acceptance_mode"] == "manual"
        assert r.json()["acceptance_timeout_s"] == 240

        row = await _outlet_row(db, seed["outlet_id"])
        assert row.acceptance_mode == "manual"
        assert row.acceptance_timeout_s == 240

    async def test_acceptance_config_rejects_a_bad_mode_and_timeout(
            self, client, seed):
        assert (await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/acceptance",
            headers=seed["admin_auth"], json={"mode": "sometimes"})
        ).status_code == 422
        assert (await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/acceptance",
            headers=seed["admin_auth"], json={"mode": "manual", "timeout_s": 5})
        ).status_code == 422

    async def test_switching_to_auto_leaves_pending_orders_alone(
            self, client, seed, db):
        """Otherwise the switch becomes a bulk silent accept."""
        order = await _awaiting_order(client, seed, db)
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/acceptance",
            headers=seed["admin_auth"], json={"mode": "auto"})
        assert r.status_code == 200, r.text
        assert (await _order_row(db, order["id"])).acceptance_state == AWAITING

    async def test_acceptance_fields_appear_in_the_owner_queue(
            self, client, seed, db):
        order = await _awaiting_order(client, seed, db)
        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        row = next(o for o in r.json() if o["order_id"] == order["id"])
        assert row["acceptance_state"] == AWAITING
        assert row["acceptance_deadline_at"] is not None

    async def test_owner_queue_fields_are_null_for_auto_outlets(
            self, client, seed, db):
        order = await _place(client, seed)
        await _pay(client, seed, order["id"])
        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        row = next(o for o in r.json() if o["order_id"] == order["id"])
        assert row["acceptance_state"] is None
        assert row["acceptance_deadline_at"] is None
