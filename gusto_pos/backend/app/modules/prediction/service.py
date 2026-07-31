"""PredictionService — deterministic shadow-mode engine (design doc §11–§16).

Phase 1 / v1: NO machine learning. A deterministic station kitchen model, a
haversine travel fallback (Maps blocked → always source='haversine_fallback',
degraded=true, σ inflated ≥2× per FR-P4), a queueing load model, and a Monte-
Carlo departure decision. Everything runs synchronously on read/write — no
scheduler, no broker (§17). All timing is server-side UTC.

SHADOW MODE: predictions are computed and written to order_twin / prediction_log,
but the customer only ever sees a WIDE range (§16) — never a departure window,
σ, or confidence. Graduation to a visible window (Step 7) is held.

NOTE on §14.1: the doc labels `α·E[(arrival−ready)⁺]` as "customer waits", but by
§4's definitions and §14.2 (α=3 ⇒ *customer* waiting is 3× costlier) the customer
waits when food is ready AFTER arrival, i.e. (ready−arrival)⁺. We implement the
semantically-correct version: α on customer-wait, β on food-hold.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# --- tunables (§11.3, §12, §13, §14.2 — "config not code") ------------------
PREP_INFLATION = 1.35                 # §11.4 owner-supplied optimism correction
DEFAULT_ACCEPTANCE_LAG_S = 120
BASE_SIGMA_S = 300                    # §11.3 base_sigma seed (cold start)
COLD_START_TRUST_ORDERS = 30         # §11.3 / NFR-16

# station -> (base_prep_s, occupancy_s, hold_tolerance_s) defaults when the
# owner hasn't supplied per-dish values on menu_items.
STATION_DEFAULTS = {
    "griddle":  (240, 240, 300),
    "fryer":    (300, 180, 240),
    "wok":      (300, 240, 600),
    "tandoor":  (420, 300, 900),
    "cold":     (120,  60, 1800),
    "beverage": (90,   45, 1800),
    "other":    (300, 240, 900),
}

MODE_SPEED_MPS = {"walk": 1.4, "bike": 8.3, "car": 6.9, "auto": 5.5, "bus": 4.2}
DEFAULT_MODE = "bike"
LASTMILE_S = 90                       # §12.3
TRAVEL_RESIDUAL_SIGMA_S = 240         # travel_bias default residual_sigma_s
HAVERSINE_SIGMA_INFLATE = 2.0         # FR-P4

COST_ALPHA = 3.0                      # §14.2 customer-wait weight
COST_GAMMA = 15.0                     # §14.2 quality-failure weight
COST_BETA_BASE = 1.0
COST_BETA_REF_HOLD_S = 600            # β scales with inverse hold tolerance
MC_DRAWS = 200                        # FR-D1
DEPART_BUCKETS_MIN = list(range(0, 46, 5))   # now .. +45 min, 5-min steps

DEFAULT_THROUGHPUT_CAP_PER_HR = 20    # §13, inferred later
DEFAULT_MEAN_SERVICE_S = 300
RHO_SUPPRESS = 0.85                   # FR-P6

TWIN_STALE_S = 120                    # NFR-6
Q80_Z = 0.8416                        # z for the 80th percentile (FR-M2)

_ACTIVE = ("PAID", "RECEIVED", "PREPARING")


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _resolve_item(station, base_prep, occupancy, hold_tol):
    """Owner-supplied values get ×1.35 (§11.4); missing values fall back to the
    per-station defaults (already realistic, not re-inflated)."""
    st = station or "other"
    d_base, d_occ, d_hold = STATION_DEFAULTS.get(st, STATION_DEFAULTS["other"])
    base = int(base_prep * PREP_INFLATION) if base_prep is not None else d_base
    occ = int(occupancy * PREP_INFLATION) if occupancy is not None else d_occ
    hold = int(hold_tol) if hold_tol is not None else d_hold
    return st, base, occ, hold


class PredictionService:
    # ------------------------------ Load (§13) -----------------------------
    @staticmethod
    async def predict_load(db: AsyncSession, outlet_id, exclude_order_id=None):
        """Returns (backlog_per_station_seconds: dict, utilisation ρ)."""
        rows = (await db.execute(text("""
            SELECT coalesce(mi.station,'other') AS station, mi.base_prep_seconds,
                   mi.occupancy_seconds, mi.hold_tolerance_seconds,
                   coalesce(mi.is_batchable,false) AS is_batchable,
                   oi.quantity, co.id AS order_id
            FROM customer_orders co
            JOIN customer_order_items oi ON oi.customer_order_id = co.id
            JOIN menu_items mi ON mi.id = oi.menu_item_id
            WHERE co.outlet_id = :o AND co.status = ANY(:st)
              AND (CAST(:ex AS uuid) IS NULL OR co.id <> CAST(:ex AS uuid))
        """), {"o": str(outlet_id), "st": list(_ACTIVE),
               "ex": str(exclude_order_id) if exclude_order_id else None})).fetchall()
        backlog = defaultdict(float)
        active_orders = set()
        batch_seen = defaultdict(dict)  # station -> {order: max_occ} for batchable
        for r in rows:
            active_orders.add(r.order_id)
            st, _base, occ, _hold = _resolve_item(
                r.station, r.base_prep_seconds, r.occupancy_seconds, r.hold_tolerance_seconds)
            if r.is_batchable:
                key = str(r.order_id)
                batch_seen[st][key] = max(batch_seen[st].get(key, 0), occ)
            else:
                backlog[st] += occ * r.quantity
        for st, per_order in batch_seen.items():
            backlog[st] += sum(per_order.values())
        n = len(active_orders)
        rho = (n * DEFAULT_MEAN_SERVICE_S) / (DEFAULT_THROUGHPUT_CAP_PER_HR * 3600.0)
        return dict(backlog), rho

    # ---------------------------- Kitchen (§11) ----------------------------
    @staticmethod
    async def predict_kitchen(db: AsyncSession, order_id, outlet_id, backlog, outlet_state):
        """Returns (μ_ready_s, σ_ready_s, model_version). Also stashes the order's
        min hold-tolerance on outlet_state['_hold_tolerance_s'] for the caller."""
        rows = (await db.execute(text("""
            SELECT coalesce(mi.station,'other') AS station, mi.base_prep_seconds,
                   mi.occupancy_seconds, mi.hold_tolerance_seconds,
                   coalesce(mi.is_batchable,false) AS is_batchable, oi.quantity
            FROM customer_order_items oi
            JOIN menu_items mi ON mi.id = oi.menu_item_id
            WHERE oi.customer_order_id = :o
        """), {"o": str(order_id)})).fetchall()

        station_occ = defaultdict(float)     # non-batchable Σ occ·qty
        station_batch = defaultdict(float)   # batchable max occ
        unattended_tail = 0
        hold_tol = None
        for r in rows:
            _st, base, occ, hold = _resolve_item(
                r.station, r.base_prep_seconds, r.occupancy_seconds, r.hold_tolerance_seconds)
            if r.is_batchable:
                station_batch[_st] = max(station_batch[_st], occ)
            else:
                station_occ[_st] += occ * r.quantity
            unattended_tail = max(unattended_tail, base - occ)   # §11.2 passive tail
            hold_tol = hold if hold_tol is None else min(hold_tol, hold)   # FR-D3: min
        outlet_state["_hold_tolerance_s"] = hold_tol if hold_tol is not None else 900

        stations = set(station_occ) | set(station_batch) | set(backlog)
        max_station = max(
            (backlog.get(s, 0) + station_occ.get(s, 0) + station_batch.get(s, 0)
             for s in stations), default=0)
        mu = outlet_state["acceptance_lag_s"] + max_station + unattended_tail

        sigma = float(BASE_SIGMA_S)
        if outlet_state["trusted_order_count"] < COLD_START_TRUST_ORDERS:
            sigma *= 2.0
        if outlet_state["tap_discipline"] < 0.6:
            sigma *= 1.5
        if outlet_state["rho"] > RHO_SUPPRESS:
            sigma *= 1.4
        # ×1.3 if raining — no weather source wired (Q6), so not applied.
        return float(mu), float(sigma), "kitchen_det_v1"

    # ---------------------------- Travel (§12) -----------------------------
    @staticmethod
    def predict_travel(origin_lat, origin_lng, outlet_lat, outlet_lng, mode):
        """Haversine fallback ONLY (Maps blocked). Always degraded, σ×2."""
        if None in (origin_lat, origin_lng, outlet_lat, outlet_lng):
            # No origin (e.g. location denied, FR-C6): very wide, degraded.
            return 20 * 60.0, TRAVEL_RESIDUAL_SIGMA_S * HAVERSINE_SIGMA_INFLATE * 1.5, "haversine_fallback"
        dist_km = _haversine_km(float(origin_lat), float(origin_lng),
                                float(outlet_lat), float(outlet_lng))
        speed = MODE_SPEED_MPS.get(mode or DEFAULT_MODE, MODE_SPEED_MPS[DEFAULT_MODE])
        mu = (dist_km * 1000.0) / speed + LASTMILE_S
        sigma = TRAVEL_RESIDUAL_SIGMA_S * HAVERSINE_SIGMA_INFLATE
        return float(mu), float(sigma), "haversine_fallback"

    # --------------------------- Decision (§14) ----------------------------
    @staticmethod
    def decide_departure(mu_ready, sigma_ready, mu_travel, sigma_travel, hold_tol_s, now):
        """Monte-Carlo scan of departure buckets; returns
        (depart_start, depart_end, chosen_bucket_min, cost, per_bucket)."""
        beta = COST_BETA_BASE * (COST_BETA_REF_HOLD_S / max(hold_tol_s, 60))
        sr = max(sigma_ready, 1.0)
        st = max(sigma_travel, 1.0)
        best_b, best_cost = 0, float("inf")
        per_bucket = {}
        for b in DEPART_BUCKETS_MIN:
            b_s = b * 60
            wait = hold = fail = 0.0
            for _ in range(MC_DRAWS):
                ready = random.gauss(mu_ready, sr)          # s-from-now until ready
                arrival = b_s + random.gauss(mu_travel, st)  # s-from-now until arrival
                if ready > arrival:
                    wait += (ready - arrival)                # CUSTOMER waits (α)
                else:
                    hold += (arrival - ready)                # food HOLDS (β)
                    if (arrival - ready) > hold_tol_s:
                        fail += 1                            # quality failure (γ)
            n = float(MC_DRAWS)
            cost = COST_ALPHA * (wait / n) + beta * (hold / n) + COST_GAMMA * (fail / n)
            per_bucket[b] = round(cost, 2)
            if cost < best_cost:
                best_cost, best_b = cost, b
        # FR-D2 / §14.3: asymmetric window, biased toward leaving sooner.
        start = now + timedelta(seconds=best_b * 60 - 120)
        end = now + timedelta(seconds=best_b * 60 + 180)
        return start, end, best_b, round(best_cost, 2), per_bucket

    # --------------------- Orchestration: recompute twin -------------------
    @staticmethod
    async def recompute_twin(db: AsyncSession, order_id) -> dict | None:
        """Run the full pipeline for one order and write order_twin +
        prediction_log (+ a one-time PROMISE_ISSUED event). Shadow mode: the
        customer only ever gets `shadow_range` (§16). Best-effort — callers wrap
        this so a prediction failure never affects the order's own transaction."""
        from app.modules.prediction import events as pe

        o = (await db.execute(text("""
            SELECT co.id, co.outlet_id, co.status, co.transport_mode,
                   co.origin_lat, co.origin_lng, o.latitude AS olat, o.longitude AS olng
            FROM customer_orders co JOIN outlets o ON o.id = co.outlet_id
            WHERE co.id = :id
        """), {"id": str(order_id)})).first()
        if not o:
            return None

        rel = (await db.execute(text(
            "SELECT trusted_order_count, tap_discipline FROM outlet_reliability WHERE outlet_id = :o"
        ), {"o": str(o.outlet_id)})).first()
        lag = (await db.execute(text("""
            SELECT percentile_disc(0.5) WITHIN GROUP (
                     ORDER BY EXTRACT(EPOCH FROM (a.occurred_at - c.occurred_at)))
            FROM order_events a
            JOIN order_events c ON c.order_id = a.order_id AND c.event_type='ORDER_CREATED'
            WHERE a.outlet_id = :o AND a.event_type='ORDER_ACCEPTED'
        """), {"o": str(o.outlet_id)})).scalar()

        backlog, rho = await PredictionService.predict_load(db, o.outlet_id, exclude_order_id=order_id)
        outlet_state = {
            "acceptance_lag_s": int(lag) if lag is not None else DEFAULT_ACCEPTANCE_LAG_S,
            "trusted_order_count": int(rel.trusted_order_count) if rel else 0,
            "tap_discipline": float(rel.tap_discipline) if rel and rel.tap_discipline is not None else 1.0,
            "rho": rho,
        }
        mu_ready, sigma_ready, kv = await PredictionService.predict_kitchen(
            db, order_id, o.outlet_id, backlog, outlet_state)
        hold_tol = outlet_state["_hold_tolerance_s"]
        mu_travel, sigma_travel, tsrc = PredictionService.predict_travel(
            o.origin_lat, o.origin_lng, o.olat, o.olng, o.transport_mode)

        now = datetime.now(timezone.utc)
        d_start, d_end, bucket, cost, buckets = PredictionService.decide_departure(
            mu_ready, sigma_ready, mu_travel, sigma_travel, hold_tol, now)

        sigma_gap = math.sqrt(sigma_ready ** 2 + sigma_travel ** 2)
        ready_p50 = now + timedelta(seconds=mu_ready)
        ready_p80 = now + timedelta(seconds=mu_ready + Q80_Z * sigma_ready)
        arrival_p50 = now + timedelta(seconds=bucket * 60 + mu_travel)
        promise_start = ready_p80                                   # FR-M2: anchor q80
        promise_end = promise_start + timedelta(seconds=max(300, sigma_gap))

        # §16 shadow range shown to the customer (wide, rounded to 5 min).
        lo = max(5, int(round((mu_ready) / 60 / 5)) * 5)
        hi = max(lo + 5, int(round((mu_ready + 2 * sigma_ready) / 60 / 5)) * 5)

        degraded = tsrc == "haversine_fallback"
        risk = "high" if rho > RHO_SUPPRESS else ("medium" if sigma_gap > 420 else "low")

        inputs = {
            "mu_ready_s": round(mu_ready), "sigma_ready_s": round(sigma_ready),
            "mu_travel_s": round(mu_travel), "sigma_travel_s": round(sigma_travel),
            "rho": round(rho, 3), "backlog_s": {k: round(v) for k, v in backlog.items()},
            "acceptance_lag_s": outlet_state["acceptance_lag_s"],
            "trusted_order_count": outlet_state["trusted_order_count"],
            "tap_discipline": outlet_state["tap_discipline"],
            "hold_tolerance_s": hold_tol, "transport_mode": o.transport_mode,
            "has_origin": o.origin_lat is not None, "travel_source": tsrc,
            "minute_of_day": now.hour * 60 + now.minute, "dow": now.weekday(),
            "shadow_range_min": [lo, hi], "cost_by_bucket": buckets,
        }
        model_versions = {"kitchen": kv, "travel": "travel_haversine_v1",
                          "load": "load_v1", "decision": "decision_mc_v1",
                          "promise": "promise_q80_v1"}
        feature_hash = hashlib.sha256(
            json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()[:16]

        await db.execute(text("""
            INSERT INTO order_twin
                (order_id, ready_p50, ready_p80, ready_sigma_s, arrival_p50, travel_sigma_s,
                 travel_source, sigma_gap_s, depart_window_start, depart_window_end,
                 promise_start, promise_end, promise_issued_at, hold_tolerance_s,
                 risk_level, degraded, inputs, model_versions, last_recomputed_at, stale_after)
            VALUES
                (:id, :rp50, :rp80, :rsig, :ap50, :tsig, :tsrc, :sgap, :ds, :de,
                 :ps, :pe, now(), :hold, :risk, :deg, CAST(:inp AS jsonb), CAST(:mv AS jsonb),
                 now(), :stale)
            ON CONFLICT (order_id) DO UPDATE SET
                version = order_twin.version + 1,
                ready_p50=:rp50, ready_p80=:rp80, ready_sigma_s=:rsig, arrival_p50=:ap50,
                travel_sigma_s=:tsig, travel_source=:tsrc, sigma_gap_s=:sgap,
                depart_window_start=:ds, depart_window_end=:de,
                promise_start=:ps, promise_end=:pe, hold_tolerance_s=:hold,
                risk_level=:risk, degraded=:deg, inputs=CAST(:inp AS jsonb),
                model_versions=CAST(:mv AS jsonb), last_recomputed_at=now(), stale_after=:stale
        """), {
            "id": str(order_id), "rp50": ready_p50, "rp80": ready_p80,
            "rsig": round(sigma_ready), "ap50": arrival_p50, "tsig": round(sigma_travel),
            "tsrc": tsrc, "sgap": round(sigma_gap), "ds": d_start, "de": d_end,
            "ps": promise_start, "pe": promise_end, "hold": hold_tol, "risk": risk,
            "deg": degraded, "inp": json.dumps(inputs), "mv": json.dumps(model_versions),
            "stale": now + timedelta(seconds=TWIN_STALE_S),
        })

        for predictor, mu, sig, out in [
            ("kitchen", mu_ready, sigma_ready, {"model": kv}),
            ("travel", mu_travel, sigma_travel, {"source": tsrc}),
            ("load", None, None, {"rho": round(rho, 3), "backlog_s": {k: round(v) for k, v in backlog.items()}}),
            ("decision", bucket * 60, None, {"depart_bucket_min": bucket, "cost": cost,
                                             "window": [d_start.isoformat(), d_end.isoformat()]}),
            ("promise", None, None, {"promise": [promise_start.isoformat(), promise_end.isoformat()],
                                     "shadow_range_min": [lo, hi]}),
        ]:
            await db.execute(text("""
                INSERT INTO prediction_log
                    (order_id, outlet_id, predictor, model_version, mu_seconds, sigma_seconds, features, output)
                VALUES (:o, :ou, :p, :mv, :mu, :sig, CAST(:f AS jsonb), CAST(:out AS jsonb))
            """), {"o": str(order_id), "ou": str(o.outlet_id), "p": predictor,
                   "mv": model_versions.get(predictor, "v1"),
                   "mu": round(mu) if mu is not None else None,
                   "sig": round(sig) if sig is not None else None,
                   "f": json.dumps(inputs), "out": json.dumps(out)})

        # FR-E4 / FR-M1: PROMISE_ISSUED once (revisions = Step 7, held).
        already = (await db.execute(text(
            "SELECT 1 FROM order_events WHERE order_id=:o AND event_type='PROMISE_ISSUED' LIMIT 1"
        ), {"o": str(order_id)})).first()
        if not already:
            await pe.write_event(
                db, order_id, pe.PROMISE_ISSUED, actor_type="system", source="system",
                outlet_id=o.outlet_id,
                payload={"promise_start": promise_start.isoformat(),
                         "promise_end": promise_end.isoformat(),
                         "model_versions": model_versions, "feature_hash": feature_hash,
                         "shadow_range_min": [lo, hi]})
        await db.commit()
        return {"shadow_range_min": [lo, hi], "degraded": degraded, "risk_level": risk}

    # ------------------- Outcome + trust scoring (§10, FR-T) ---------------
    @staticmethod
    async def compute_outcome(db: AsyncSession, order_id) -> None:
        """On a terminal order, score trust per §10 and write order_outcome, then
        refresh outlet_reliability. Best-effort (callers wrap in try/except)."""
        evs = (await db.execute(text("""
            SELECT event_type, occurred_at, recorded_at, source, actor_type, payload
            FROM order_events WHERE order_id=:o ORDER BY seq
        """), {"o": str(order_id)})).fetchall()
        if not evs:
            return
        first = {}
        for e in evs:
            first.setdefault(e.event_type, e)
        outlet_id = (await db.execute(text(
            "SELECT outlet_id FROM customer_orders WHERE id=:o"), {"o": str(order_id)})).scalar()

        def t(name):
            return first[name].occurred_at if name in first else None
        created, accepted = t("ORDER_CREATED"), t("ORDER_ACCEPTED")
        prep, ready = t("PREP_STARTED"), t("ORDER_READY")
        departed, arrived = t("CUSTOMER_DEPARTED"), t("CUSTOMER_ARRIVED")
        collected = t("PICKUP_VERIFIED")
        secs = lambda a, b: (b - a).total_seconds() if a and b else None

        # --- kitchen trust (§10) ---
        kt, fails = 1.0, []
        if "PREP_STARTED" not in first:
            kt = 0.0; fails.append("prep_started_absent")
        if accepted and prep and (prep - accepted).total_seconds() < 15:
            kt = 0.0; fails.append("prep_started_lt_15s")   # incl. inferred (prep==accept)
        if prep and ready and (ready - prep).total_seconds() < 60:
            kt = 0.0; fails.append("ready_lt_60s")
        if ready and collected and (collected - ready).total_seconds() < 30:
            kt *= 0.3; fails.append("ready_at_handover")
        for e in evs:
            if e.event_type in ("ORDER_ACCEPTED", "PREP_STARTED", "ORDER_READY") and \
               (e.recorded_at - e.occurred_at).total_seconds() > 120:
                kt *= 0.6; fails.append("kitchen_event_late_sync"); break

        # --- travel trust (§10) ---
        tt = 1.0
        if "CUSTOMER_DEPARTED" not in first:
            tt = 0.0; fails.append("no_departure")
        elif first["CUSTOMER_DEPARTED"].source == "inferred":
            tt *= 0.7; fails.append("departure_inferred")
        if arrived:
            av = first["CUSTOMER_ARRIVED"]
            acc = (av.payload if isinstance(av.payload, dict) else json.loads(av.payload)).get("accuracy_m")
            if av.source != "geofence" or (acc is not None and acc > 200):
                tt *= 0.5; fails.append("arrival_low_confidence")
        twin = (await db.execute(text(
            "SELECT travel_source, promise_start, promise_end FROM order_twin WHERE order_id=:o"
        ), {"o": str(order_id)})).first()
        if twin and twin.travel_source == "haversine_fallback":
            tt *= 0.5; fails.append("haversine_fallback")   # always true while Maps blocked

        # --- customer trust (§10) ---
        ct = 1.0
        wf = None
        if "WAIT_FEEDBACK" in first:
            wp = first["WAIT_FEEDBACK"].payload
            wf = (wp if isinstance(wp, dict) else json.loads(wp)).get("bucket")
            gap = secs(arrived, collected)
            if gap is not None and wf:
                lo = {"0": 0, "1-3": 60, "3-5": 180, "5+": 300}.get(wf, 0)
                if abs(gap - lo) > 240 + 120:   # >4 min beyond the bucket
                    ct *= 0.5; fails.append("wait_feedback_contradiction")

        promise_kept = None
        if twin and twin.promise_start and twin.promise_end and ready:
            promise_kept = twin.promise_start <= ready <= twin.promise_end
        interval_score = None
        if twin and twin.promise_start and twin.promise_end and ready:
            width = (twin.promise_end - twin.promise_start).total_seconds()
            pen = 0.0
            if ready < twin.promise_start:
                pen = (2 / COST_ALPHA) * (twin.promise_start - ready).total_seconds()
            elif ready > twin.promise_end:
                pen = (2 / COST_ALPHA) * (ready - twin.promise_end).total_seconds()
            interval_score = round(width + pen, 2)

        await db.execute(text("""
            INSERT INTO order_outcome
                (order_id, outlet_id, accepted_at, prep_started_at, ready_at, departed_at,
                 arrived_at, collected_at, actual_prep_s, actual_travel_s, actual_hold_s,
                 counter_wait_s, promise_start, promise_end, promise_kept, interval_score,
                 wait_feedback, kitchen_trust, travel_trust, customer_trust, trust_failures)
            VALUES
                (:o, :ou, :acc, :prep, :ready, :dep, :arr, :col, :aprep, :atrav, :ahold,
                 :cw, :ps, :pe, :pk, :isc, :wf, :kt, :tt, :ct, CAST(:tf AS jsonb))
            ON CONFLICT (order_id) DO UPDATE SET
                ready_at=:ready, collected_at=:col, actual_prep_s=:aprep,
                actual_travel_s=:atrav, counter_wait_s=:cw, promise_kept=:pk,
                interval_score=:isc, wait_feedback=:wf, kitchen_trust=:kt,
                travel_trust=:tt, customer_trust=:ct, trust_failures=CAST(:tf AS jsonb)
        """), {
            "o": str(order_id), "ou": str(outlet_id), "acc": accepted, "prep": prep,
            "ready": ready, "dep": departed, "arr": arrived, "col": collected,
            "aprep": _i(secs(prep or accepted, ready)), "atrav": _i(secs(departed, arrived)),
            "ahold": _i(secs(ready, collected)), "cw": _i(secs(arrived, collected)),
            "ps": twin.promise_start if twin else None, "pe": twin.promise_end if twin else None,
            "pk": promise_kept, "isc": interval_score, "wf": wf,
            "kt": round(kt, 2), "tt": round(tt, 2), "ct": round(ct, 2),
            "tf": json.dumps(fails),
        })
        await PredictionService.refresh_outlet_reliability(db, outlet_id)
        await db.commit()

    @staticmethod
    async def refresh_outlet_reliability(db: AsyncSession, outlet_id) -> None:
        """Recompute the per-outlet quality summary from order_outcome (§8.7)."""
        await db.execute(text("""
            INSERT INTO outlet_reliability
                (outlet_id, trusted_order_count, median_prep_s, prep_residual_sigma_s,
                 interval_score_p50, fulfillment_rate, median_window_width_s,
                 tap_discipline, shadow_mode, updated_at)
            SELECT
                :o,
                count(*) FILTER (WHERE kitchen_trust >= 0.7),
                percentile_disc(0.5) WITHIN GROUP (ORDER BY actual_prep_s)
                    FILTER (WHERE kitchen_trust >= 0.7),
                NULL,
                percentile_disc(0.5) WITHIN GROUP (ORDER BY interval_score)
                    FILTER (WHERE interval_score IS NOT NULL),
                avg(CASE WHEN promise_kept THEN 1 ELSE 0 END)::numeric(4,3),
                percentile_disc(0.5) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (promise_end - promise_start)))::int,
                (SELECT avg(CASE WHEN has_all THEN 1 ELSE 0 END)::numeric(3,2) FROM (
                    SELECT bool_and(t) AS has_all FROM (
                        SELECT oe.order_id,
                               bool_or(event_type='ORDER_ACCEPTED') AND
                               bool_or(event_type='PREP_STARTED') AND
                               bool_or(event_type='ORDER_READY') AS t
                        FROM order_events oe WHERE oe.outlet_id=:o GROUP BY oe.order_id
                    ) x) y),
                true, now()
            FROM order_outcome WHERE outlet_id = :o
            ON CONFLICT (outlet_id) DO UPDATE SET
                trusted_order_count=EXCLUDED.trusted_order_count,
                median_prep_s=EXCLUDED.median_prep_s,
                interval_score_p50=EXCLUDED.interval_score_p50,
                fulfillment_rate=EXCLUDED.fulfillment_rate,
                median_window_width_s=EXCLUDED.median_window_width_s,
                tap_discipline=EXCLUDED.tap_discipline, updated_at=now()
        """), {"o": str(outlet_id)})


def _i(v):
    return int(v) if v is not None else None
