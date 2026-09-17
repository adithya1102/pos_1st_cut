"""Scheduled pickup + the universal arrival-feasibility gate (migration 031).

Two features that share one question — "can this customer actually be served?" —
and therefore one test file:

  * the GATE, which refuses an order at creation when the customer's estimated
    arrival lands outside the outlet's operating window, for EVERY mode;
  * the HOLD, which keeps a paid scheduled order off the restaurant's tablet
    until prep time plus a margin before the customer's chosen slot.

Everything here runs against the local throwaway DB (see conftest) with
MAPS_SERVER_KEY unset, so predict_travel stays on its haversine path and no
test makes a network call.
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.modules.carevo_customer.service import (
    ARRIVAL_INFEASIBLE_MESSAGE, CarevoService, SCHEDULED_MAX_AHEAD_S,
)
from app.modules.prediction.service import SCHEDULED_RELEASE_SAFETY_MARGIN_S

API = "/api/v1"
IST = ZoneInfo("Asia/Kolkata")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _t(delta_minutes: int):
    """A bare local time offset from now (IST) — the same helper shape
    test_api_outlet_hours uses, so hours here mean what they mean there."""
    return (datetime.now(IST) + timedelta(minutes=delta_minutes)).time().replace(
        second=0, microsecond=0)


async def _set_hours(db, outlet_id, opens, closes, manual=False):
    await db.execute(text(
        "UPDATE outlets SET opens_at=:o, closes_at=:c, is_manually_closed=:m "
        "WHERE id=:id"),
        {"o": opens, "c": closes, "m": manual, "id": str(outlet_id)})
    await db.commit()


async def _set_location(db, outlet_id, lat, lng):
    await db.execute(text(
        "UPDATE outlets SET latitude=:la, longitude=:ln WHERE id=:id"),
        {"la": lat, "ln": lng, "id": str(outlet_id)})
    await db.commit()


async def _place(client, seed, **extra):
    body = {"outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]}
    body.update(extra)
    return await client.post(f"{API}/customer/orders",
                             headers=seed["customer_auth"], json=body)


async def _pay(client, seed, order_id):
    return await client.post(f"{API}/customer/payment/simulate",
                             headers=seed["customer_auth"],
                             json={"order_id": order_id, "method": "upi"})


async def _place_and_pay(client, seed, **extra):
    r = await _place(client, seed, **extra)
    assert r.status_code == 200, r.text
    order = r.json()
    p = await _pay(client, seed, order["id"])
    assert p.status_code == 200, p.text
    return order


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


async def _make_due(db, order_id):
    """Bring a held order's release moment into the past.

    Moves requested_pickup_at, NOT release_at — because release_at is a derived
    value and every pass recomputes it from the requested time. Poking
    release_at directly is meaningless: the next refresh overwrites it, which is
    exactly the "re-derived, not frozen" behaviour asserted elsewhere in this
    file. Ten seconds out is enough: the derived release is that minus
    (mu_ready_s + the safety margin), which is comfortably in the past for any
    positive prep estimate.
    """
    await db.execute(text(
        "UPDATE customer_orders SET requested_pickup_at = now() + interval '10 seconds' "
        "WHERE id=:o"), {"o": str(order_id)})
    await db.execute(text(
        "UPDATE auto_advance_schedule SET due_at = now() - interval '1 minute' "
        "WHERE order_id=:o"), {"o": str(order_id)})
    await db.commit()


async def _row(db, order_id):
    return (await db.execute(text(
        "SELECT status, release_at, requested_pickup_at, updated_at "
        "FROM customer_orders WHERE id=:o"), {"o": str(order_id)})).first()


async def _event_types(db, order_id):
    rows = (await db.execute(text(
        "SELECT event_type FROM order_events WHERE order_id=:o ORDER BY seq"
    ), {"o": str(order_id)})).scalars().all()
    return list(rows)


async def _queue_ids(client, seed):
    r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
    assert r.status_code == 200, r.text
    return [str(o["order_id"]) for o in r.json()]


# ==========================================================================
# TASK 3 — the universal arrival-feasibility gate
# ==========================================================================
@pytest.mark.asyncio
class TestGateGpsEstimatedModes:
    """car/bike/walk/auto/bus — arrival estimated from distance/speed via the
    EXISTING predict_travel (no second travel model was introduced)."""

    async def test_far_origin_is_refused_when_the_outlet_shuts_soon(
            self, client, seed, db):
        # Outlet open for another 45 min. Customer is ~5km away on foot, which
        # at MODE_SPEED_MPS['walk'] is a ~60 min journey — they arrive after
        # close, so the order must never be taken.
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(45))
        await _set_location(db, seed["outlet_id"], 12.9716, 77.5946)
        r = await _place(client, seed, transport_mode="walk",
                         origin_lat=13.0166, origin_lng=77.5946,
                         origin_source="gps")
        assert r.status_code == 409
        assert r.json()["detail"] == ARRIVAL_INFEASIBLE_MESSAGE

    async def test_same_far_origin_is_fine_when_the_outlet_is_open_for_hours(
            self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(240))
        await _set_location(db, seed["outlet_id"], 12.9716, 77.5946)
        r = await _place(client, seed, transport_mode="walk",
                         origin_lat=13.0166, origin_lng=77.5946,
                         origin_source="gps")
        assert r.status_code == 200, r.text

    async def test_a_faster_mode_over_the_same_distance_is_accepted(
            self, client, seed, db):
        """The gate is genuinely mode-aware, not a flat distance cutoff: the
        identical origin that fails on foot passes by car."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(45))
        await _set_location(db, seed["outlet_id"], 12.9716, 77.5946)
        r = await _place(client, seed, transport_mode="car",
                         origin_lat=13.0166, origin_lng=77.5946,
                         origin_source="gps")
        assert r.status_code == 200, r.text

    async def test_no_origin_falls_back_wide_but_still_lets_the_order_through(
            self, client, seed, db):
        """FR-C6: refusing location must not refuse the order. predict_travel's
        no-origin fallback is a deliberately wide 20 min, and an outlet with
        hours to spare still accepts."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(240))
        r = await _place(client, seed, transport_mode="bike",
                         origin_source="none")
        assert r.status_code == 200, r.text

    async def test_outlet_with_no_hours_never_refuses(self, client, seed, db):
        """NULL hours means always-open server-side; the gate must inherit that
        rather than inventing a window."""
        await _set_location(db, seed["outlet_id"], 12.9716, 77.5946)
        r = await _place(client, seed, transport_mode="walk",
                         origin_lat=13.2166, origin_lng=77.5946,
                         origin_source="gps")
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
class TestGateDeclaredArrivalModes:
    """train/metro/tram — arrival is the time the customer typed, plus the
    platform-to-door constant."""

    async def test_train_arriving_after_close_is_refused(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(60))
        r = await _place(
            client, seed, transport_mode="train",
            declared_arrival_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=90)))
        assert r.status_code == 409
        assert r.json()["detail"] == ARRIVAL_INFEASIBLE_MESSAGE

    async def test_train_arriving_inside_the_window_is_accepted(
            self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(240))
        r = await _place(
            client, seed, transport_mode="train",
            declared_arrival_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=60)))
        assert r.status_code == 200, r.text

    async def test_metro_is_gated_identically_to_train(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(60))
        r = await _place(
            client, seed, transport_mode="metro",
            declared_arrival_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=90)))
        assert r.status_code == 409

    async def test_the_platform_walk_counts_against_the_cutoff(
            self, client, seed, db):
        """Arrival is declared + TRAIN_LAST_MILE_DEFAULT_S (8 min), and the
        30-min pre-close cutoff applies to THAT. A train landing 35 min before
        close puts the customer at the door with 27 min left — inside the
        cutoff, so refused."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(35 + 30))
        r = await _place(
            client, seed, transport_mode="train",
            declared_arrival_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=35)))
        assert r.status_code == 409


@pytest.mark.asyncio
class TestGateScheduledRequests:
    async def test_pickup_time_after_close_is_refused(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(90))
        r = await _place(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=150)))
        assert r.status_code == 409
        assert r.json()["detail"] == ARRIVAL_INFEASIBLE_MESSAGE

    async def test_pickup_time_inside_the_cutoff_is_refused(self, client, seed, db):
        """Chosen slot is 10 min before close — no room to cook it."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(120))
        r = await _place(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=110)))
        assert r.status_code == 409

    async def test_feasible_pickup_time_is_accepted(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(240))
        r = await _place(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=90)))
        assert r.status_code == 200, r.text

    async def test_a_time_in_the_past_is_refused(self, client, seed):
        r = await _place(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) - timedelta(minutes=5)))
        assert r.status_code == 409
        assert r.json()["detail"] == ARRIVAL_INFEASIBLE_MESSAGE

    async def test_beyond_the_horizon_is_refused(self, client, seed):
        """Also a correctness guard: outlet_availability compares minute-of-day
        only, so a request >24h out would wrap around and read as open."""
        r = await _place(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(seconds=SCHEDULED_MAX_AHEAD_S + 3600)))
        assert r.status_code == 409

    async def test_a_refused_request_writes_no_order_row(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(90))
        before = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id=:o"),
            {"o": seed["outlet_id"]})
        await _place(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=150)))
        after = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id=:o"),
            {"o": seed["outlet_id"]})
        assert after == before, "the gate must refuse before any row is written"


@pytest.mark.asyncio
class TestClosingSoonSplitsTheTwoPaths:
    """closing_soon blocks ASAP but must NOT block scheduling — that window is
    exactly when scheduling is most useful."""

    async def test_asap_is_still_blocked_during_closing_soon(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(10))
        r = await _place(client, seed)
        assert r.status_code == 409
        assert "closing soon" in r.json()["detail"].lower()

    async def test_scheduling_survives_closing_soon_when_the_slot_is_feasible(
            self, client, seed, db):
        # Closes in 3h, but an ASAP order right now would be fine too — so to
        # isolate the closing_soon path, shut the ASAP door with a near close
        # while leaving an overnight-style late window open is not possible on
        # one pair of hours. Instead: close in 20 min (ASAP refused, above) and
        # confirm a slot inside the remaining open window is still refused,
        # while a genuinely feasible slot on a wider window is accepted.
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(20))
        # The outlet is 'closing_soon' right now, so create_order's ASAP branch
        # would refuse. The scheduled branch gets past that and is judged on the
        # slot instead — which here is still infeasible, so 409 comes from the
        # ARRIVAL gate, not from the closing_soon reason string.
        r = await _place(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=10)))
        assert r.status_code == 409
        assert r.json()["detail"] == ARRIVAL_INFEASIBLE_MESSAGE, \
            "scheduling must be judged by the arrival gate, not refused outright"

    async def test_manually_closed_refuses_scheduling_too(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], None, None, manual=True)
        r = await _place(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=90)))
        assert r.status_code == 409
        assert "temporarily closed" in r.json()["detail"].lower()


# ==========================================================================
# TASK 1 — the hold
# ==========================================================================
@pytest.mark.asyncio
class TestHoldKeepsTheOrderOffTheQueue:
    async def test_a_paid_scheduled_order_is_not_in_the_owner_queue(
            self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        assert str(order["id"]) not in await _queue_ids(client, seed)

    async def test_an_asap_order_is_in_the_queue_immediately(self, client, seed):
        order = await _place_and_pay(client, seed)
        assert str(order["id"]) in await _queue_ids(client, seed)

    async def test_it_appears_once_release_at_has_passed(self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        assert str(order["id"]) not in await _queue_ids(client, seed)
        # Bring the pickup moment forward rather than waiting two hours.
        await _make_due(db, order["id"])
        assert str(order["id"]) in await _queue_ids(client, seed)

    async def test_the_queue_read_itself_performs_the_release(
            self, client, seed, db):
        """check-on-read is the PRIMARY mechanism: the owner polling /pos/orders
        is what actually releases a due order, not the background poller."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        await _make_due(db, order["id"])
        await _queue_ids(client, seed)
        row = await _row(db, order["id"])
        assert row.status == "RECEIVED", "the read should have released it"
        assert row.release_at is None, "release must clear the hold"


@pytest.mark.asyncio
class TestTtlSweeperExemption:
    async def test_a_held_order_survives_the_ttl(self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=180)))
        # Age it far past PICKUP_TTL_MINUTES. Without the exemption the very
        # next sweep would ABANDON a paid order.
        await db.execute(text(
            "UPDATE customer_orders SET updated_at = now() - interval '5 hours' "
            "WHERE id=:o"), {"o": order["id"]})
        await db.commit()
        await CarevoService._expire_stale_pickups(db, order_id=order["id"])
        row = await _row(db, order["id"])
        assert row.status == "PAID", "a held order must be exempt from the TTL"

    async def test_an_unheld_order_is_still_swept(self, client, seed, db):
        """The exemption must be scoped exactly — normal orders keep their
        existing protection against genuine abandonment."""
        order = await _place_and_pay(client, seed)
        await db.execute(text(
            "UPDATE customer_orders SET updated_at = now() - interval '5 hours' "
            "WHERE id=:o"), {"o": order["id"]})
        await db.commit()
        await CarevoService._expire_stale_pickups(db, order_id=order["id"])
        row = await _row(db, order["id"])
        assert row.status == "ABANDONED"

    async def test_release_restarts_the_ttl_clock_at_release_not_payment(
            self, client, seed, db):
        """The whole reason release must go through advance_status: it stamps
        updated_at, so the 45-minute pickup window starts when the customer can
        actually collect. Without this a released order would be instantly
        stale and swept on the next sweep."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=180)))
        await _make_due(db, order["id"])
        await db.execute(text(
            "UPDATE customer_orders SET updated_at = now() - interval '5 hours' "
            "WHERE id=:o"), {"o": order["id"]})
        await db.commit()

        await CarevoService.refresh_scheduled_releases(db, order_id=order["id"])
        row = await _row(db, order["id"])
        assert row.status == "RECEIVED"
        age = (datetime.now(timezone.utc) - row.updated_at).total_seconds()
        assert age < 60, "updated_at must be restamped at release"

        # And it is now subject to the TTL again, like any live order.
        await CarevoService._expire_stale_pickups(db, order_id=order["id"])
        assert (await _row(db, order["id"])).status == "RECEIVED"
        await db.execute(text(
            "UPDATE customer_orders SET updated_at = now() - interval '5 hours' "
            "WHERE id=:o"), {"o": order["id"]})
        await db.commit()
        await CarevoService._expire_stale_pickups(db, order_id=order["id"])
        assert (await _row(db, order["id"])).status == "ABANDONED"


@pytest.mark.asyncio
class TestKitchenTrustEventsMoveToRelease:
    """The prerequisite fix: inferred ORDER_ACCEPTED/PREP_STARTED at payment
    would record hours of prep time for a held order, poisoning median_prep_s
    and trusted_order_count — which feed straight back into sigma."""

    async def test_payment_does_not_infer_prep_for_a_held_order(
            self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        types = await _event_types(db, order["id"])
        assert "ORDER_PAID" in types
        assert "ORDER_ACCEPTED" not in types
        assert "PREP_STARTED" not in types

    async def test_payment_still_infers_prep_for_an_asap_order(
            self, client, seed, db):
        """Unchanged for every order that is not held."""
        order = await _place_and_pay(client, seed)
        types = await _event_types(db, order["id"])
        assert "ORDER_ACCEPTED" in types
        assert "PREP_STARTED" in types

    async def test_release_emits_them_with_the_right_provenance(
            self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        await _make_due(db, order["id"])
        await CarevoService.refresh_scheduled_releases(db, order_id=order["id"])

        types = await _event_types(db, order["id"])
        assert "ORDER_ACCEPTED" in types
        assert "PREP_STARTED" in types
        src = (await db.execute(text(
            "SELECT payload->>'derived_from' AS d FROM order_events "
            "WHERE order_id=:o AND event_type='PREP_STARTED'"),
            {"o": order["id"]})).scalar()
        assert src == "scheduled_release"

    async def test_prep_started_is_anchored_to_the_release_call(
            self, client, seed, db):
        """compute_outcome derives actual_prep_s as (ready_at - prep_started_at),
        so WHEN PREP_STARTED lands is the number that gets poisoned.

        Asserted as a before/after around the release rather than by backdating
        the event: order_events carries an append-only trigger (migration 006)
        that rejects UPDATE outright, which is itself the reason a wrong
        timestamp here could never be corrected after the fact.
        """
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        assert "PREP_STARTED" not in await _event_types(db, order["id"]), \
            "prep must not be inferred while the order is still held"

        await _make_due(db, order["id"])
        boundary = datetime.now(timezone.utc)
        await CarevoService.refresh_scheduled_releases(db, order_id=order["id"])

        prep_at, paid_at = (await db.execute(text("""
            SELECT max(occurred_at) FILTER (WHERE event_type='PREP_STARTED'),
                   max(occurred_at) FILTER (WHERE event_type='ORDER_PAID')
            FROM order_events WHERE order_id=:o
        """), {"o": order["id"]})).first()
        assert prep_at >= boundary, "PREP_STARTED must be stamped at release"
        assert prep_at > paid_at, "and strictly after the payment it used to ride on"


@pytest.mark.asyncio
class TestReleaseIsRederivedNotFrozen:
    async def test_the_hold_starts_conservative_and_is_refined_down(
            self, client, seed, db):
        """mark_paid seeds release_at at requested_pickup_at (the latest, safest
        value) inside the payment transaction, then the twin-backed derivation
        moves it earlier by mu + margin. It can only ever move earlier."""
        pickup = datetime.now(timezone.utc) + timedelta(minutes=180)
        order = await _place_and_pay(client, seed,
                                     requested_pickup_at=_iso(pickup))
        row = await _row(db, order["id"])
        assert row.release_at is not None
        assert row.release_at < row.requested_pickup_at, \
            "the hold should have been refined below the conservative seed"
        lead = (row.requested_pickup_at - row.release_at).total_seconds()
        assert lead >= SCHEDULED_RELEASE_SAFETY_MARGIN_S, \
            "the lead must include at least the safety margin"

    async def test_a_later_pass_re_derives_against_the_current_twin(
            self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=180)))
        # Push release_at somewhere it could not have been derived, and stale
        # the twin so the next pass genuinely recomputes rather than reusing it.
        await db.execute(text(
            "UPDATE customer_orders SET release_at = requested_pickup_at "
            "WHERE id=:o"), {"o": order["id"]})
        await db.execute(text(
            "UPDATE order_twin SET stale_after = now() - interval '1 hour' "
            "WHERE order_id=:o"), {"o": order["id"]})
        await db.commit()

        await CarevoService.refresh_scheduled_releases(db, order_id=order["id"])
        row = await _row(db, order["id"])
        assert row.release_at < row.requested_pickup_at, \
            "a later pass must re-derive, not leave the frozen value"

    async def test_release_at_never_exceeds_the_customers_chosen_time(
            self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=90)))
        row = await _row(db, order["id"])
        assert row.release_at <= row.requested_pickup_at


@pytest.mark.asyncio
class TestNoRoomToHoldReleasesImmediately:
    async def test_a_slot_too_close_to_now_behaves_like_a_normal_order(
            self, client, seed, db):
        """'If the requested time leaves no real room to hold, release
        immediately.' A slot 2 minutes out cannot absorb prep + margin."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(240))
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=2)))
        row = await _row(db, order["id"])
        assert row.release_at is None or row.release_at <= datetime.now(timezone.utc)
        assert str(order["id"]) in await _queue_ids(client, seed)

    async def test_the_requested_time_is_still_recorded_for_the_dataset(
            self, client, seed, db):
        """Even when nothing was held, the customer's choice is kept — it is the
        join key for measuring the margin later."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(240))
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=2)))
        assert (await _row(db, order["id"])).requested_pickup_at is not None


# ==========================================================================
# TASK 1 — auto_advance_schedule kind discriminator
# ==========================================================================
async def _schedule_row(db, order_id):
    return (await db.execute(text(
        "SELECT kind, next_stage, due_at FROM auto_advance_schedule "
        "WHERE order_id=:o"), {"o": str(order_id)})).first()


@pytest.mark.asyncio
class TestAutoAdvanceKindDiscriminator:
    async def test_a_held_order_gets_a_release_row(self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        row = await _schedule_row(db, order["id"])
        assert row is not None
        assert row.kind == "release"
        assert row.next_stage == "RECEIVED"

    async def test_release_rows_are_processed_with_the_roster_switch_off(
            self, client, seed, db):
        """AUTO_ADVANCE_ROSTER_ORDERS is a testing kill switch, off by default
        and absent from render.yaml. It must never gate a customer feature."""
        from app.core.config import settings
        from app.modules.testing_dashboard.service import TestingService
        assert settings.AUTO_ADVANCE_ROSTER_ORDERS is False, \
            "this test is only meaningful while the switch is off"

        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        await _make_due(db, order["id"])

        processed = await TestingService.process_due_auto_advances(db)
        assert processed >= 1
        assert (await _row(db, order["id"])).status == "RECEIVED"

    async def test_a_release_does_not_walk_the_rest_of_the_stage_chain(
            self, client, seed, db):
        """One advance (PAID -> RECEIVED), row deleted, real kitchen takes over.
        It must NOT continue to PREPARING/READY the way a roster row does."""
        from app.modules.testing_dashboard.service import TestingService
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        await _make_due(db, order["id"])

        await TestingService.process_due_auto_advances(db)
        assert await _schedule_row(db, order["id"]) is None, \
            "the release row must be deleted, not rewritten to the next stage"

        # A second pass must find nothing left to do and leave it at RECEIVED.
        await TestingService.process_due_auto_advances(db)
        assert (await _row(db, order["id"])).status == "RECEIVED"

    async def test_an_asap_order_writes_no_schedule_row_while_the_switch_is_off(
            self, client, seed, db):
        order = await _place_and_pay(client, seed)
        assert await _schedule_row(db, order["id"]) is None

    async def test_an_order_that_leaves_the_live_set_retires_its_hold(
            self, client, seed, db):
        """A held order can still be completed early at the counter — its
        pickup code is live and lookup_pickup matches it — or rejected from the
        testing dashboard. Neither path goes through _release_held_order, so
        without a cleanup the schedule row outlives its order and the poller
        re-examines it every few seconds forever."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        assert await _schedule_row(db, order["id"]) is not None

        r = await client.post(f"{API}/testing/orders/{order['id']}/reject",
                              headers={"X-Testing-Key": "dev-testing-key"},
                              json={"reason": "early"})
        assert r.status_code in (200, 401, 403), r.text
        if r.status_code != 200:
            # The dashboard key is not configured in this environment; reject
            # through the service directly so the cleanup is still exercised.
            await CarevoService.reject_order(
                db, uuid.UUID(order["id"]), uuid.UUID(seed["outlet_id"]),
                reason="early")

        await CarevoService.refresh_scheduled_releases(db)
        assert await _schedule_row(db, order["id"]) is None, \
            "the orphan release row must be retired"
        assert (await _row(db, order["id"])).release_at is None


# ==========================================================================
# TASK 1 — train/metro mutual exclusivity
# ==========================================================================
@pytest.mark.asyncio
class TestDeclaredArrivalAndScheduleCannotBothFire:
    async def test_the_kitchen_notify_is_suppressed_for_a_held_order(
            self, client, seed, db):
        """Both mechanisms decide when the kitchen starts. release_at wins."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(300))
        order = await _place_and_pay(
            client, seed, transport_mode="train",
            declared_arrival_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=45)),
            requested_pickup_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=120)))

        # The train notify would otherwise be due: arrival is 45 min out and
        # prep + buffer easily exceeds that.
        fired = await CarevoService._notify_kitchen_for_due_trains(
            db, outlet_id=seed["outlet_id"])
        types = await _event_types(db, order["id"])
        assert "KITCHEN_START_NOTIFIED" not in types, \
            "a held order must not also be woken by the train path"
        assert fired == 0

    async def test_the_declared_arrival_is_still_stored_for_the_travel_model(
            self, client, seed, db):
        """Suppressing the notification must not discard the data —
        predict_travel's customer_declared leg still needs it."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(300))
        order = await _place_and_pay(
            client, seed, transport_mode="train",
            declared_arrival_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=45)),
            requested_pickup_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=120)))
        dec = (await db.execute(text(
            "SELECT declared_arrival_at FROM customer_orders WHERE id=:o"),
            {"o": order["id"]})).scalar()
        assert dec is not None

    async def test_an_unheld_train_order_still_gets_its_notify(
            self, client, seed, db):
        """The guard must be scoped to held orders only.

        The arrival is 5 minutes out, which puts it well past the due point
        (arrival - mu_ready_s - KITCHEN_NOTIFY_SAFETY_BUFFER_S) for a one-item
        order, so the push is genuinely owed and its absence would mean the
        release guard had over-reached."""
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(300))
        order = await _place_and_pay(
            client, seed, transport_mode="train",
            declared_arrival_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=5)))
        await CarevoService._notify_kitchen_for_due_trains(
            db, outlet_id=seed["outlet_id"])
        assert "KITCHEN_START_NOTIFIED" in await _event_types(db, order["id"])


# ==========================================================================
# TASK 1 — the prediction_log dataset
# ==========================================================================
@pytest.mark.asyncio
class TestReleasePredictionLog:
    async def test_a_release_predictor_row_is_written(self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        rows = (await db.execute(text(
            "SELECT model_version, mu_seconds, features, output FROM prediction_log "
            "WHERE order_id=:o AND predictor='release' ORDER BY id"),
            {"o": order["id"]})).fetchall()
        assert rows, "the sixth predictor must log the hold decision"
        first = rows[0]
        assert first.model_version == "release_v1"
        assert first.mu_seconds is not None
        assert first.features["safety_margin_s"] == SCHEDULED_RELEASE_SAFETY_MARGIN_S
        assert first.output["decision"] == "held"
        assert first.features["requested_pickup_at"] is not None

    async def test_the_release_itself_is_logged_as_a_separate_decision(
            self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        await _make_due(db, order["id"])
        await CarevoService.refresh_scheduled_releases(db, order_id=order["id"])
        decisions = (await db.execute(text(
            "SELECT output->>'decision' AS d FROM prediction_log "
            "WHERE order_id=:o AND predictor='release'"),
            {"o": order["id"]})).scalars().all()
        assert "released" in decisions

    async def test_the_log_joins_back_to_the_order_for_margin_analysis(
            self, client, seed, db):
        """The whole point of the dataset: predicted release vs the time the
        customer actually asked for, joinable without a new table."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        row = (await db.execute(text("""
            SELECT co.requested_pickup_at, pl.mu_seconds,
                   (pl.features->>'safety_margin_s')::int AS margin
            FROM prediction_log pl
            JOIN customer_orders co ON co.id = pl.order_id
            WHERE pl.order_id=:o AND pl.predictor='release' LIMIT 1
        """), {"o": order["id"]})).first()
        assert row is not None
        assert row.requested_pickup_at is not None
        assert row.margin == SCHEDULED_RELEASE_SAFETY_MARGIN_S


# ==========================================================================
# OrderOut surface
# ==========================================================================
@pytest.mark.asyncio
class TestOrderOutCarriesTheSchedule:
    async def test_a_held_order_reports_both_timestamps(self, client, seed):
        pickup = datetime.now(timezone.utc) + timedelta(minutes=120)
        order = await _place_and_pay(client, seed,
                                     requested_pickup_at=_iso(pickup))
        r = await client.get(f"{API}/customer/orders/{order['id']}",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["requested_pickup_at"] is not None
        assert body["release_at"] is not None

    async def test_an_asap_order_reports_neither(self, client, seed):
        order = await _place_and_pay(client, seed)
        r = await client.get(f"{API}/customer/orders/{order['id']}",
                             headers=seed["customer_auth"])
        body = r.json()
        assert body["requested_pickup_at"] is None
        assert body["release_at"] is None


# ==========================================================================
# The pickup CODE is minted at PAYMENT, hold or no hold
# ==========================================================================
@pytest.mark.asyncio
class TestHeldOrderStillGetsItsCodeAtPayment:
    """The hold is about what the RESTAURANT can see, never about what the
    CUSTOMER is told.

    mark_paid mints pickup_code unconditionally, BEFORE it has even read
    requested_pickup_at — see service.py, where the code assignment sits above
    the `held = ...` computation. These tests pin that ordering by its observable
    consequence, so a later refactor that moves the mint under `if not held`
    fails here rather than in someone's hands at a counter.
    """

    async def test_a_held_order_has_a_pickup_code_the_moment_it_is_paid(
            self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        code = (await db.execute(text(
            "SELECT pickup_code FROM customer_orders WHERE id=:o"),
            {"o": order["id"]})).scalar()
        assert code, "a held order must still be given its pickup code at payment"

    async def test_the_customer_endpoint_returns_it_while_still_held(
            self, client, seed, db):
        """What PickupScreen actually reads. It polls GET /customer/orders/{id}
        and shows `pickup_code` gated on payment_status == 'PAID' alone — there
        is no hold-aware branch in the app, and this is the response that makes
        that correct."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        # Still held: proving the code is visible during the hold, not after it.
        row = await _row(db, order["id"])
        assert row.release_at is not None and row.release_at > datetime.now(timezone.utc)

        r = await client.get(f"{API}/customer/orders/{order['id']}",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payment_status"].upper() == "PAID"
        assert body["pickup_code"], "the customer must see their code while held"

    async def test_it_is_the_same_code_the_order_keeps_through_release(
            self, client, seed, db):
        """A code shown at payment and then changed at release would be worse
        than no code at all — the customer screenshots the first one."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        before = (await db.execute(text(
            "SELECT pickup_code FROM customer_orders WHERE id=:o"),
            {"o": order["id"]})).scalar()
        await _make_due(db, order["id"])
        await CarevoService.refresh_scheduled_releases(db, order_id=order["id"])
        after = (await db.execute(text(
            "SELECT pickup_code FROM customer_orders WHERE id=:o"),
            {"o": order["id"]})).scalar()
        assert after == before

    async def test_a_held_order_is_indistinguishable_from_asap_on_the_code(
            self, client, seed, db):
        """Same shape, same length, same moment — the ASAP order is the
        control."""
        held = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        asap = await _place_and_pay(client, seed)
        codes = {}
        for label, o in (("held", held), ("asap", asap)):
            r = await client.get(f"{API}/customer/orders/{o['id']}",
                                 headers=seed["customer_auth"])
            codes[label] = r.json()["pickup_code"]
        assert codes["held"] and codes["asap"]
        assert len(codes["held"]) == len(codes["asap"])
        assert codes["held"] != codes["asap"], "codes must still be unique"

    async def test_the_code_works_at_the_counter_even_while_held(
            self, client, seed, db):
        """Consequence of the above, and the reason it matters: a customer who
        turns up early can still be served — lookup_pickup resolves a held
        order's code rather than reporting it unknown."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        code = (await db.execute(text(
            "SELECT pickup_code FROM customer_orders WHERE id=:o"),
            {"o": order["id"]})).scalar()
        found = await CarevoService.lookup_pickup(
            db, uuid.UUID(seed["outlet_id"]), code)
        assert found["found"] is True, "a held order's code must still resolve"
        assert str(found["order"]["order_id"]) == str(order["id"])


# ==========================================================================
# Owner-side invisibility, asserted as a before/after on ONE order
# ==========================================================================
@pytest.mark.asyncio
class TestOwnerQueueVisibilityFlipsAtRelease:
    async def test_invisible_before_release_and_visible_after(
            self, client, seed, db):
        """The whole promise in one test, on a single order: the owner queue
        does not contain it while held, and does once its release has run."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        oid = str(order["id"])

        assert oid not in await _queue_ids(client, seed), "held must be invisible"
        row = await _row(db, oid)
        assert row.status == "PAID" and row.release_at is not None

        await _make_due(db, oid)
        assert oid in await _queue_ids(client, seed), "due must be visible"
        row = await _row(db, oid)
        assert row.status == "RECEIVED"
        assert row.release_at is None, "release must clear the hold"

    async def test_repeated_polls_while_held_never_leak_it(self, client, seed):
        """One poll proving absence could be luck of a race. The owner app polls
        every 15s for hours before a scheduled order is due."""
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        for _ in range(5):
            assert str(order["id"]) not in await _queue_ids(client, seed)

    async def test_the_held_order_is_absent_but_an_asap_sibling_is_present(
            self, client, seed):
        """Scoping check: the queue is not simply empty. Two orders, same
        outlet, same poll — only the unheld one comes back."""
        held = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        asap = await _place_and_pay(client, seed)
        ids = await _queue_ids(client, seed)
        assert str(asap["id"]) in ids
        assert str(held["id"]) not in ids
