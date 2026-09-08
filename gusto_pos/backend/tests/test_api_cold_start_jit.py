"""Timing Engine addendum Item 2 — cold-start JIT fallback, SHADOW MODE.

The path under test fires only when BOTH halves of a conjunction hold:

    trusted_order_count(outlet) < 30   AND   hold_tolerance_seconds(order) < 300

and when it does it writes order_twin.scheduled_prep_start_at /
latest_safe_start_at and emits one PREP_SCHEDULED event. It must change nothing
about when food is actually cooked.

The regression class at the bottom is the important half of this file: it
asserts that mark_paid, Item 1 (train mode) and Item 3 (ITEM_UNAVAILABLE
cutoff) all behave exactly as they did before.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from .conftest import API

from app.modules.prediction.service import (
    COLD_START_JIT_HOLD_TRIGGER_S,
    COLD_START_TRUST_ORDERS,
    STATION_DEFAULTS,
    PredictionService,
    _jit_station_buffer_s,
)


# ------------------------------- helpers ------------------------------------
async def _set_item_timing(db, item_id, *, hold_s, station="fryer",
                           base_prep_s=300, occupancy_s=180):
    """Give the seeded dish real PE timing fields. The seed fixture leaves them
    NULL, which resolves to STATION_DEFAULTS rather than anything test-specific."""
    await db.execute(text("""
        UPDATE menu_items
        SET station = :st, base_prep_seconds = :bp, occupancy_seconds = :occ,
            hold_tolerance_seconds = :hold, is_batchable = false
        WHERE id = :i"""),
        {"st": station, "bp": base_prep_s, "occ": occupancy_s,
         "hold": hold_s, "i": str(item_id)})
    await db.commit()


async def _set_trust(db, outlet_id, count):
    """Set the outlet's trusted_order_count directly.

    Written as an upsert because outlet_reliability has no row until an order
    has actually completed — a cold outlet is the ABSENT-row case, which is
    exactly the state this feature targets."""
    await db.execute(text("""
        INSERT INTO outlet_reliability (outlet_id, trusted_order_count, tap_discipline,
                                        shadow_mode, updated_at)
        VALUES (:o, :c, 1.0, true, now())
        ON CONFLICT (outlet_id) DO UPDATE SET trusted_order_count = :c"""),
        {"o": str(outlet_id), "c": count})
    await db.commit()


async def _twin(db, order_id):
    return (await db.execute(text("""
        SELECT scheduled_prep_start_at, latest_safe_start_at, hold_tolerance_s
        FROM order_twin WHERE order_id = :o"""), {"o": str(order_id)})).first()


async def _prep_scheduled_events(db, order_id):
    return (await db.execute(text("""
        SELECT payload FROM order_events
        WHERE order_id = :o AND event_type = 'PREP_SCHEDULED' ORDER BY seq"""),
        {"o": str(order_id)})).fetchall()


# ----------------------------- the gate -------------------------------------
class TestColdStartJitGate:
    async def test_fires_when_cold_and_fragile(self, db, seed, paid_order):
        """Both halves true -> columns populated, event emitted."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)

        await PredictionService.recompute_twin(db, paid_order["id"])

        row = await _twin(db, paid_order["id"])
        assert row.scheduled_prep_start_at is not None
        assert row.latest_safe_start_at is not None
        assert len(await _prep_scheduled_events(db, paid_order["id"])) == 1

    async def test_does_not_fire_when_food_tolerates_holding(
        self, db, seed, paid_order
    ):
        """Cold outlet, but the dish sits happily for 30 min. JIT is pointless
        here — half the conjunction is false, so nothing is written."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=1800, station="cold")
        await _set_trust(db, seed["outlet_id"], 0)

        await PredictionService.recompute_twin(db, paid_order["id"])

        row = await _twin(db, paid_order["id"])
        assert row.scheduled_prep_start_at is None
        assert row.latest_safe_start_at is None
        assert await _prep_scheduled_events(db, paid_order["id"]) == []

    async def test_does_not_fire_when_outlet_is_warm(self, db, seed, paid_order):
        """Fragile food, but the outlet has enough history to trust. The real
        model applies; the cold-start FALLBACK must stay out of the way."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], COLD_START_TRUST_ORDERS + 5)

        await PredictionService.recompute_twin(db, paid_order["id"])

        row = await _twin(db, paid_order["id"])
        assert row.scheduled_prep_start_at is None
        assert await _prep_scheduled_events(db, paid_order["id"]) == []

    async def test_boundaries_are_strict_less_than(self, db, seed, paid_order):
        """Exactly AT each threshold must NOT fire — the spec says '< 30' and
        '< 300', and an off-by-one here silently changes who gets scheduled."""
        await _set_item_timing(
            db, seed["menu_item_id"], hold_s=COLD_START_JIT_HOLD_TRIGGER_S)
        await _set_trust(db, seed["outlet_id"], COLD_START_TRUST_ORDERS)

        await PredictionService.recompute_twin(db, paid_order["id"])

        row = await _twin(db, paid_order["id"])
        assert row.scheduled_prep_start_at is None, \
            "hold == trigger and trust == threshold must not fire"


# --------------------------- scheduling maths -------------------------------
class TestScheduleValues:
    async def test_scheduled_never_after_latest_safe(self, db, seed, paid_order):
        """The window must be coherent even when mu_ready is large relative to
        the time remaining — an inverted window would poison later analysis."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=60,
                               base_prep_s=3600, occupancy_s=3600)
        await _set_trust(db, seed["outlet_id"], 0)

        await PredictionService.recompute_twin(db, paid_order["id"])

        row = await _twin(db, paid_order["id"])
        assert row.scheduled_prep_start_at <= row.latest_safe_start_at

    async def test_scheduled_start_is_never_in_the_past(self, db, seed, paid_order):
        """A kitchen cannot act on a start time that has already gone.

        The order below wants 2h of prep, so the unclamped schedule lands far in
        the past — this asserts the clamp catches it.

        Timestamp taken from PYTHON, not `SELECT now()`. The clamp in
        recompute_twin uses datetime.now(timezone.utc), and Postgres reads a
        finer-grained clock than Python does on Windows (~15ms timer
        granularity), so a DB-vs-Python comparison disagrees by a few
        milliseconds at random — that flaked roughly 1 run in 4 with a ~3ms
        delta. Same clock on both sides makes the assertion mean what it says.
        """
        await _set_item_timing(db, seed["menu_item_id"], hold_s=60,
                               base_prep_s=7200, occupancy_s=7200)
        await _set_trust(db, seed["outlet_id"], 0)

        before = datetime.now(timezone.utc)
        await PredictionService.recompute_twin(db, paid_order["id"])

        row = await _twin(db, paid_order["id"])
        assert row.scheduled_prep_start_at >= before

    async def test_buffer_is_capped_by_hold_tolerance(self, db, seed, paid_order):
        """When the dish's own tolerance is tighter than the station pool
        default, the dish wins. 90s on a fryer (pool default 240s) -> 90s."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=90, station="fryer")
        await _set_trust(db, seed["outlet_id"], 0)

        await PredictionService.recompute_twin(db, paid_order["id"])

        payload = (await _prep_scheduled_events(db, paid_order["id"]))[0].payload
        assert payload["effective_buffer_s"] == 90
        assert payload["station_buffer_s"] == _jit_station_buffer_s("fryer")
        assert payload["effective_buffer_s"] < payload["station_buffer_s"]

    async def test_station_pool_default_binds_when_it_is_tighter(
        self, db, seed, paid_order
    ):
        """The point of making the buffer station-specific.

        A fryer's pool default is 240s. A dish claiming 280s of tolerance still
        gets a 240s buffer, because the pool-level expectation for that station
        is tighter than the dish's own optimistic claim. Under the flat 300s
        constant this order would have got 280s.

        This is the ONLY band where the change is observable: the gate already
        requires hold_tol < 300, and every station default except fryer (240)
        and griddle (300) is >= 300, so elsewhere the dish's own value still
        wins exactly as before.
        """
        await _set_item_timing(db, seed["menu_item_id"], hold_s=280, station="fryer")
        await _set_trust(db, seed["outlet_id"], 0)

        await PredictionService.recompute_twin(db, paid_order["id"])

        payload = (await _prep_scheduled_events(db, paid_order["id"]))[0].payload
        assert payload["station_buffer_s"] == 240
        assert payload["effective_buffer_s"] == 240, \
            "station pool default must bind when tighter than the dish's claim"
        assert payload["effective_buffer_s"] < payload["hold_tolerance_s"]

    async def test_buffer_differs_by_station(self, db, seed, paid_order):
        """A tandoor tolerates far more waiting than a fryer, so the two must
        not receive the same buffer — that is the whole change."""
        assert _jit_station_buffer_s("fryer") != _jit_station_buffer_s("tandoor")

        await _set_item_timing(db, seed["menu_item_id"], hold_s=120, station="tandoor")
        await _set_trust(db, seed["outlet_id"], 0)

        await PredictionService.recompute_twin(db, paid_order["id"])

        payload = (await _prep_scheduled_events(db, paid_order["id"]))[0].payload
        assert payload["binding_station"] == "tandoor"
        assert payload["station_buffer_s"] == STATION_DEFAULTS["tandoor"][2]

    async def test_unknown_station_falls_back_to_other(self):
        """Mirrors _resolve_item: a missing/unrecognised station resolves to
        'other' rather than raising."""
        assert _jit_station_buffer_s(None) == STATION_DEFAULTS["other"][2]
        assert _jit_station_buffer_s("nonexistent_station") == STATION_DEFAULTS["other"][2]


# ------------------------- station dimension (Task 3) -----------------------
class TestStationPayload:
    async def test_payload_carries_station_dimension(self, db, seed, paid_order):
        """order_twin is order-level; the EVENT is where the per-station shape
        lives, so the simultaneous-start modelling gap stays measurable."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120, station="tandoor")
        await _set_trust(db, seed["outlet_id"], 0)

        await PredictionService.recompute_twin(db, paid_order["id"])

        payload = (await _prep_scheduled_events(db, paid_order["id"]))[0].payload
        assert payload["binding_station"] == "tandoor"
        assert "tandoor" in payload["station_load_s"]
        assert isinstance(payload["station_load_s"]["tandoor"], (int, float))

    async def test_payload_is_explicitly_marked_shadow(self, db, seed, paid_order):
        """So no later reader mistakes a logged schedule for an instruction the
        kitchen was actually given."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)

        await PredictionService.recompute_twin(db, paid_order["id"])

        payload = (await _prep_scheduled_events(db, paid_order["id"]))[0].payload
        assert payload["shadow_mode"] is True
        assert payload["reason"] == "cold_start_jit"


# ------------------------------ idempotency ---------------------------------
class TestEmittedOnce:
    async def test_repeated_recompute_emits_one_event(self, db, seed, paid_order):
        """recompute_twin runs on every status read. Re-emitting would turn an
        append-only event log into a poll log."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)

        for _ in range(3):
            await PredictionService.recompute_twin(db, paid_order["id"])

        assert len(await _prep_scheduled_events(db, paid_order["id"])) == 1


# ============================================================================
# REGRESSION — shadow mode means none of this changed
# ============================================================================
class TestNothingElseChanged:
    async def test_mark_paid_still_emits_its_inferred_events(
        self, db, seed, paid_order
    ):
        """mark_paid is explicitly out of scope. It still infers ORDER_ACCEPTED
        and PREP_STARTED from payment, exactly as before — PREP_SCHEDULED is an
        ADDITION to the log, never a replacement."""
        rows = (await db.execute(text("""
            SELECT event_type, source FROM order_events
            WHERE order_id = :o AND event_type IN ('ORDER_ACCEPTED','PREP_STARTED')"""),
            {"o": str(paid_order["id"])})).fetchall()
        kinds = {r.event_type for r in rows}
        assert kinds == {"ORDER_ACCEPTED", "PREP_STARTED"}
        assert all(r.source == "inferred" for r in rows)

    async def test_prep_started_timing_is_untouched_by_the_schedule(
        self, db, seed, paid_order
    ):
        """The whole point of shadow mode: PREP_STARTED already exists from
        payment and firing the JIT path must not move, delay or re-write it."""
        before = (await db.execute(text(
            "SELECT occurred_at FROM order_events "
            "WHERE order_id=:o AND event_type='PREP_STARTED'"),
            {"o": str(paid_order["id"])})).scalar()

        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)
        await PredictionService.recompute_twin(db, paid_order["id"])

        after = (await db.execute(text(
            "SELECT occurred_at FROM order_events "
            "WHERE order_id=:o AND event_type='PREP_STARTED'"),
            {"o": str(paid_order["id"])})).scalar()
        assert before == after

    async def test_order_status_is_unchanged_by_the_schedule(
        self, db, seed, paid_order
    ):
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)
        before = (await db.execute(text(
            "SELECT status FROM customer_orders WHERE id=:o"),
            {"o": str(paid_order["id"])})).scalar()

        await PredictionService.recompute_twin(db, paid_order["id"])

        after = (await db.execute(text(
            "SELECT status FROM customer_orders WHERE id=:o"),
            {"o": str(paid_order["id"])})).scalar()
        assert before == after

    async def test_departure_window_still_produced_normally(
        self, db, seed, paid_order
    ):
        """Item 2 must NOT unlock or gate the departure window — that stays
        behind the existing 300-order graduation gate in carevo_admin, which
        this change does not touch."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)

        res = await PredictionService.recompute_twin(db, paid_order["id"])

        assert "shadow_range_min" in res
        row = (await db.execute(text(
            "SELECT depart_window_start, depart_window_end FROM order_twin "
            "WHERE order_id=:o"), {"o": str(paid_order["id"])})).first()
        assert row.depart_window_start is not None
        assert row.depart_window_end is not None

    async def test_promise_issued_still_emitted_once(self, db, seed, paid_order):
        """FR-E4/FR-M1. The new emission sits beside this one and must not
        disturb its once-only guard."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)

        for _ in range(2):
            await PredictionService.recompute_twin(db, paid_order["id"])

        n = (await db.execute(text(
            "SELECT count(*) FROM order_events "
            "WHERE order_id=:o AND event_type='PROMISE_ISSUED'"),
            {"o": str(paid_order["id"])})).scalar()
        assert n == 1

    async def test_item1_train_mode_declared_arrival_still_honoured(
        self, db, seed, paid_order
    ):
        """Item 1 regression: a train order still predicts travel from the
        customer's declared arrival, with the JIT path also active."""
        await db.execute(text("""
            UPDATE customer_orders
            SET transport_mode = 'train', declared_arrival_at = now() + interval '40 minutes'
            WHERE id = :o"""), {"o": str(paid_order["id"])})
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)
        await db.commit()

        await PredictionService.recompute_twin(db, paid_order["id"])

        inputs = (await db.execute(text(
            "SELECT inputs FROM order_twin WHERE order_id=:o"),
            {"o": str(paid_order["id"])})).scalar()
        assert inputs["transport_mode"] == "train"

    async def test_item3_unavailable_cutoff_still_enforced(
        self, client, db, seed, paid_order
    ):
        """Item 3 regression: marking an item unavailable is still refused once
        the order is READY, with the JIT path having run."""
        await _set_item_timing(db, seed["menu_item_id"], hold_s=120)
        await _set_trust(db, seed["outlet_id"], 0)
        await PredictionService.recompute_twin(db, paid_order["id"])

        await db.execute(text(
            "UPDATE customer_orders SET status='READY' WHERE id=:o"),
            {"o": str(paid_order["id"])})
        await db.commit()

        r = await client.post(
            f"{API}/pos/orders/{paid_order['id']}/notify",
            headers=seed["owner_auth"],
            json={"type": "item_unavailable", "item_id": seed["menu_item_id"]})
        assert r.status_code in (400, 409, 422), \
            f"cutoff not enforced, got {r.status_code}: {r.text}"
