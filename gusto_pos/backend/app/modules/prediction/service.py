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

# --- train mode (addendum Item 1) -------------------------------------------
# Leg A is the customer's OWN stated arrival time. There is no rail API and no
# timetable behind it, so σ must reflect self-reported human data, not a
# punctual-train assumption:
#   * people round to the nearest 5-10 min when typing a time
#   * they state the SCHEDULED arrival, not the actual one
#   * Indian suburban rail routinely runs several minutes late
#   * the walk from platform to gate is inside neither leg
# 900s (15 min) is therefore the floor, not a best guess — deliberately wider
# than haversine's inflated residual (240×2 = 480s), because a wrong guess here
# means food cooked too early and sitting. Tunable, not magic: raise it if
# promise_kept rate for train orders comes in low.
TRAIN_DECLARED_SIGMA_S = 900

# Platform -> restaurant door. Per-outlet override lives in outlet_config under
# `train_last_mile_seconds`; this is the fallback when an outlet has no row,
# which is every outlet today (the table is empty). 8 min covers a typical
# station-adjacent walk without pretending to know the specific outlet.
TRAIN_LAST_MILE_DEFAULT_S = 480
TRAIN_LAST_MILE_CONFIG_KEY = "train_last_mile_seconds"

# Subtracted from declared arrival when deciding WHEN to tell the kitchen to
# start, on top of the prep estimate. Absorbs: staff not looking at the tablet
# the instant it buzzes, and the prep estimate itself being optimistic. Errs
# toward telling them early — food ready slightly ahead beats a customer whose
# train arrived on time waiting at the counter.
KITCHEN_NOTIFY_SAFETY_BUFFER_S = 300

# --- cold-start JIT fallback (addendum Item 2) — SHADOW MODE ONLY ------------
# Fires only when BOTH hold: the outlet has too little history to trust its
# timing (trusted_order_count < COLD_START_TRUST_ORDERS) AND the order contains
# something that degrades fast (hold tolerance < COLD_START_JIT_HOLD_TRIGGER_S).
#
# NOTHING ACTS ON THIS. It writes order_twin.scheduled_prep_start_at /
# latest_safe_start_at and emits PREP_SCHEDULED. No code path reads those
# columns or that event to decide when a kitchen starts cooking — verified by
# search across the backend and all three clients. mark_paid still emits its
# inferred ORDER_ACCEPTED/PREP_STARTED exactly as before, and the departure
# window stays behind the existing 300-order graduation gate in carevo_admin.
#
# THE BUFFER IS NOT A NEW NUMBER, AND IT IS PER-STATION. The master
# timing-engine doc (§11.3/§11.4) is not in this repo — searched again, still
# absent — so the buffer comes from STATION_DEFAULTS above, which is this
# codebase's actual "pool defaults" table: station -> (base_prep_s,
# occupancy_s, hold_tolerance_s). The buffer is that third element for the
# order's BINDING station, read through the same tuple-unpack idiom
# _resolve_item uses, with STATION_DEFAULTS["other"] as the fallback.
#
# Per-station rather than one flat number because a fryer (240s) and a tandoor
# (900s) do not tolerate the same wait, and the binding station is already
# computed for the event payload. See _jit_station_buffer_s below.
#
# The trigger below is DELIBERATELY NOT station-specific. It is a hard
# threshold from the spec, not a pool default: below 300s of hold tolerance the
# cold-start timing error (±BASE_SIGMA_S) is LARGER than the window the food can
# sit in, which is precisely when "start whenever" ruins the dish. That
# reasoning is about cold-start uncertainty, which is a property of the OUTLET's
# missing history, not of any station.
COLD_START_JIT_HOLD_TRIGGER_S = BASE_SIGMA_S    # 300

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

# --- Step 6 travel (Distance Matrix) ---------------------------------------
TRAVEL_CACHE_TTL_DAYS = 14            # quarter-hour-of-week ETAs reused ~2 weeks
_DM_TIMEOUT_S = 4.0                   # fail fast to the haversine net (FR-P4)
_IST = timedelta(hours=5, minutes=30)  # India-only deploy: bucket by local time
# our transport_mode -> Google Distance Matrix travel mode
_GMAPS_MODE = {"walk": "walking", "bike": "bicycling", "car": "driving",
               "auto": "driving", "bus": "transit"}
_GEOHASH_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _geohash6(lat: float, lng: float) -> str:
    """Standard geohash, precision 6 (~1.2km × 0.6km cell) — the travel_cache
    origin key, so nearby origins share a cached ETA."""
    lat_iv, lng_iv = [-90.0, 90.0], [-180.0, 180.0]
    bit, even, ch, out = 0, True, 0, []
    while len(out) < 6:
        if even:
            mid = (lng_iv[0] + lng_iv[1]) / 2
            if lng > mid:
                ch |= 1 << (4 - bit); lng_iv[0] = mid
            else:
                lng_iv[1] = mid
        else:
            mid = (lat_iv[0] + lat_iv[1]) / 2
            if lat > mid:
                ch |= 1 << (4 - bit); lat_iv[0] = mid
            else:
                lat_iv[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_GEOHASH_B32[ch]); bit, ch = 0, 0
    return "".join(out)


def _quarter_hour_of_week(dt_utc: datetime) -> int:
    """0..671 quarter-hour of the ISO week, in IST (local travel patterns)."""
    lt = dt_utc + _IST
    return lt.weekday() * 96 + lt.hour * 4 + lt.minute // 15


async def _distance_matrix_eta(key, olat, olng, dlat, dlng, gmode):
    """One Distance Matrix call. Returns ETA seconds, or None on ANY problem
    (timeout / transport error / non-OK element / quota) so the caller falls
    back to haversine. Uses duration_in_traffic for driving when present."""
    import httpx
    params = {
        "origins": f"{olat},{olng}",
        "destinations": f"{dlat},{dlng}",
        "mode": gmode,
        "key": key,
    }
    if gmode == "driving":
        params["departure_time"] = "now"        # unlocks duration_in_traffic
        params["traffic_model"] = "best_guess"
    try:
        async with httpx.AsyncClient(timeout=_DM_TIMEOUT_S) as client:
            r = await client.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params=params)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("status") != "OK":
            return None
        el = data["rows"][0]["elements"][0]
        if el.get("status") != "OK":
            return None
        dur = el.get("duration_in_traffic") or el.get("duration")
        secs = dur.get("value") if dur else None
        return float(secs) if secs is not None else None
    except Exception:
        return None


def _resolve_item(station, base_prep, occupancy, hold_tol):
    """Owner-supplied values get ×1.35 (§11.4); missing values fall back to the
    per-station defaults (already realistic, not re-inflated)."""
    st = station or "other"
    d_base, d_occ, d_hold = STATION_DEFAULTS.get(st, STATION_DEFAULTS["other"])
    base = int(base_prep * PREP_INFLATION) if base_prep is not None else d_base
    occ = int(occupancy * PREP_INFLATION) if occupancy is not None else d_occ
    hold = int(hold_tol) if hold_tol is not None else d_hold
    return st, base, occ, hold


def _jit_station_buffer_s(station) -> int:
    """Cold-start JIT buffer for a station (addendum Item 2).

    The pool default hold tolerance — STATION_DEFAULTS' third element, the same
    `d_hold` _resolve_item falls back to. Read by tuple unpack rather than an
    index literal so it stays correct if the tuple ever gains a field.

    `station` is the order's BINDING station (the one that sets μ_ready). None —
    an order touching no station at all — falls back to "other", matching
    _resolve_item's treatment of a missing station.
    """
    _d_base, _d_occ, d_hold = STATION_DEFAULTS.get(
        station or "other", STATION_DEFAULTS["other"])
    return d_hold


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
        per_station = {
            s: backlog.get(s, 0) + station_occ.get(s, 0) + station_batch.get(s, 0)
            for s in stations
        }
        max_station = max(per_station.values(), default=0)

        # Station dimension for the PREP_SCHEDULED payload (addendum Item 2).
        # Stashed on outlet_state, the same way _hold_tolerance_s already is,
        # because this function's contract is to return (mu, sigma, version).
        #
        # order_twin stays ORDER-level: it has one scheduled_prep_start_at
        # column, not one per station. That mismatch is a known modelling gap —
        # μ_ready assumes every station starts simultaneously, with no stagger.
        # Carrying the per-station breakdown in the EVENT payload is what makes
        # the gap measurable from logged data before anyone builds real
        # per-station scheduling on top of an order-level column.
        outlet_state["_station_load_s"] = {k: round(v) for k, v in per_station.items()}
        # The station that actually sets μ — the one a stagger model would have
        # to schedule first. None when the order touches no station at all.
        outlet_state["_binding_station"] = (
            max(per_station, key=per_station.get) if per_station else None)

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
    def _haversine_travel(origin_lat, origin_lng, outlet_lat, outlet_lng, mode):
        """FR-P4 safety net — always available, no network. Always degraded (σ×2)."""
        if None in (origin_lat, origin_lng, outlet_lat, outlet_lng):
            # No origin (e.g. location denied, FR-C6): very wide, degraded.
            return 20 * 60.0, TRAVEL_RESIDUAL_SIGMA_S * HAVERSINE_SIGMA_INFLATE * 1.5, "haversine_fallback"
        dist_km = _haversine_km(float(origin_lat), float(origin_lng),
                                float(outlet_lat), float(outlet_lng))
        speed = MODE_SPEED_MPS.get(mode or DEFAULT_MODE, MODE_SPEED_MPS[DEFAULT_MODE])
        mu = (dist_km * 1000.0) / speed + LASTMILE_S
        sigma = TRAVEL_RESIDUAL_SIGMA_S * HAVERSINE_SIGMA_INFLATE
        return float(mu), float(sigma), "haversine_fallback"

    @staticmethod
    async def train_last_mile_seconds(db, outlet_id) -> float:
        """Platform -> door constant for this outlet.

        Reads outlet_config (the existing per-outlet key/value table) rather
        than adding a column. A missing row is the NORMAL case today — the
        table is empty — so it resolves to the documented default rather than
        raising. A non-numeric value is also treated as absent: a typo in a
        config row must not take down travel prediction.
        """
        try:
            # SAVEPOINT, not a bare try/except. A failed statement aborts the
            # whole Postgres transaction, so swallowing the error here would
            # leave the caller's session poisoned — every later query in the
            # same request would then fail with MissingGreenlet, far from the
            # cause. begin_nested() confines the damage to this read.
            async with db.begin_nested():
                raw = await db.scalar(text("""
                    SELECT config_value FROM outlet_config
                    WHERE outlet_id = :o AND config_key = :k
                """), {"o": str(outlet_id), "k": TRAIN_LAST_MILE_CONFIG_KEY})
            if raw is not None:
                return float(raw)
        except Exception:
            pass
        return float(TRAIN_LAST_MILE_DEFAULT_S)

    @staticmethod
    async def predict_travel(db, outlet_id, origin_lat, origin_lng, outlet_lat,
                             outlet_lng, mode, declared_arrival_at=None):
        """Step 6 travel ETA. When MAPS_SERVER_KEY is set, use the Google Distance
        Matrix API, cached in travel_cache on (origin_geohash6, outlet_id, mode,
        quarter_hour). Haversine is ALWAYS the fallback on no-key / no-origin /
        timeout / non-OK / quota / any exception (FR-P4 — never removed).

        Returns (mu_seconds, sigma_seconds, source), source one of
        maps_live | maps_cached | haversine_fallback | customer_declared.
        """
        from app.core.config import settings

        # --- train (addendum Item 1) --------------------------------------
        # Handled FIRST and returned early: none of the machinery below
        # applies. Leg A is not a distance problem — it is a time the customer
        # typed in — so there is no origin to geocode, nothing to ask Maps, and
        # nothing worth caching. Every other mode's branch is untouched.
        #
        # `customer_declared`, not `train_schedule`: naming it after a
        # timetable would imply an external source we do not have and would
        # make this number look more trustworthy than it is.
        if (mode or "").lower() == "train":
            last_mile = await PredictionService.train_last_mile_seconds(db, outlet_id)
            declared = declared_arrival_at
            if declared is None:
                # Train selected but no arrival time stored — cannot honour the
                # mode. Fall through to the normal path rather than invent a
                # number; the caller still gets a usable (if wider) estimate.
                return PredictionService._haversine_travel(
                    origin_lat, origin_lng, outlet_lat, outlet_lng, mode)
            secs_to_arrival = max(
                0.0, (declared - datetime.now(timezone.utc)).total_seconds())
            return (float(secs_to_arrival + last_mile),
                    float(TRAIN_DECLARED_SIGMA_S),
                    "customer_declared")

        fallback = PredictionService._haversine_travel(
            origin_lat, origin_lng, outlet_lat, outlet_lng, mode)
        # Inert unless a server key is configured and we actually have an origin.
        if not settings.MAPS_SERVER_KEY or None in (origin_lat, origin_lng, outlet_lat, outlet_lng):
            return fallback

        gmode = _GMAPS_MODE.get(mode or DEFAULT_MODE, "driving")
        gh = _geohash6(float(origin_lat), float(origin_lng))
        qh = _quarter_hour_of_week(datetime.now(timezone.utc))
        real_sigma = float(TRAVEL_RESIDUAL_SIGMA_S)  # real ETA -> no σ×2 inflation

        # 1) fresh cache hit -> maps_cached
        try:
            hit = (await db.execute(text("""
                SELECT eta_seconds FROM travel_cache
                WHERE origin_geohash6=:gh AND outlet_id=:o AND mode=:m AND quarter_hour=:q
                  AND refreshed_at > now() - make_interval(days => :ttl)
            """), {"gh": gh, "o": str(outlet_id), "m": gmode, "q": qh,
                   "ttl": TRAVEL_CACHE_TTL_DAYS})).first()
            if hit is not None:
                return float(hit.eta_seconds), real_sigma, "maps_cached"
        except Exception:
            pass  # a cache read failure must never break prediction

        # 2) live Distance Matrix call (short timeout; any failure -> haversine)
        eta = await _distance_matrix_eta(
            settings.MAPS_SERVER_KEY, float(origin_lat), float(origin_lng),
            float(outlet_lat), float(outlet_lng), gmode)
        if eta is None:
            return fallback  # FR-P4 safety net

        # 3) best-effort cache upsert (never fatal)
        try:
            await db.execute(text("""
                INSERT INTO travel_cache
                    (origin_geohash6, outlet_id, mode, quarter_hour, eta_seconds, sample_count, refreshed_at)
                VALUES (:gh, :o, :m, :q, :eta, 1, now())
                ON CONFLICT (origin_geohash6, outlet_id, mode, quarter_hour)
                DO UPDATE SET eta_seconds = EXCLUDED.eta_seconds,
                              sample_count = travel_cache.sample_count + 1,
                              refreshed_at = now()
            """), {"gh": gh, "o": str(outlet_id), "m": gmode, "q": qh, "eta": int(eta)})
        except Exception:
            pass
        return float(eta), real_sigma, "maps_live"

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
                   co.declared_arrival_at,
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
        mu_travel, sigma_travel, tsrc = await PredictionService.predict_travel(
            db, o.outlet_id, o.origin_lat, o.origin_lng, o.olat, o.olng,
            o.transport_mode, declared_arrival_at=o.declared_arrival_at)

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

        # ---- cold-start JIT fallback (addendum Item 2), SHADOW MODE ONLY ----
        # Gate: too little history to trust the timing AND the food cannot sit.
        # This conjunction exists nowhere else in the repo; either half alone is
        # not enough. A cold outlet serving cold-tolerant food (hold 1800s) does
        # not need JIT, and a well-calibrated outlet does not need a fallback.
        cold_start = outlet_state["trusted_order_count"] < COLD_START_TRUST_ORDERS
        fragile = hold_tol < COLD_START_JIT_HOLD_TRIGGER_S
        if cold_start and fragile:
            # Work backwards from when the customer actually gets here.
            #
            #   start at S  ->  food ready at S + mu_ready
            #   ready before arrival -> it sits (must be <= hold_tol or quality fails)
            #   ready after arrival  -> the customer waits
            #
            # so the latest start that still avoids making them wait is
            # arrival - mu_ready, and anything earlier than that must not sit
            # longer than the food tolerates.
            ready_just_in_time = arrival_p50 - timedelta(seconds=mu_ready)

            # Buffer from the BINDING station's pool default, not a flat number:
            # a fryer (240s) and a tandoor (900s) do not tolerate the same wait.
            binding_station = outlet_state.get("_binding_station")
            station_buffer_s = _jit_station_buffer_s(binding_station)

            # Still capped by THIS order's own hold tolerance, never applied
            # blindly. Whichever of the two is tighter wins: the station default
            # is a pool-level expectation, hold_tol is what this specific dish
            # actually tolerates, and scheduling a start that guarantees the dish
            # sits past either one is the failure this path exists to prevent.
            effective_buffer_s = min(station_buffer_s, hold_tol)
            scheduled_prep_start_at = ready_just_in_time - timedelta(seconds=effective_buffer_s)
            # Never schedule a start in the past; a kitchen cannot act on it and
            # a negative lead time would poison any future analysis of this data.
            scheduled_prep_start_at = max(scheduled_prep_start_at, now)
            # Latest start that still meets arrival. Clamped so it can never
            # precede the scheduled start when mu_ready already exceeds the time
            # remaining (a late-placed order), which would otherwise log an
            # impossible window.
            latest_safe_start_at = max(ready_just_in_time, scheduled_prep_start_at)

            # Separate UPDATE rather than folding these into the INSERT above:
            # orders that do NOT meet the gate must leave both columns untouched,
            # so the non-gated path stays byte-identical to its previous behaviour.
            await db.execute(text("""
                UPDATE order_twin
                SET scheduled_prep_start_at = :sched, latest_safe_start_at = :latest
                WHERE order_id = :id
            """), {"sched": scheduled_prep_start_at,
                   "latest": latest_safe_start_at, "id": str(order_id)})

            # First PREP_SCHEDULED write site in the repo. Emitted once per
            # order, mirroring PROMISE_ISSUED below — refresh_twin runs on every
            # status read, and re-emitting would turn the append-only event log
            # into a poll log.
            already_sched = (await db.execute(text(
                "SELECT 1 FROM order_events WHERE order_id=:o "
                "AND event_type='PREP_SCHEDULED' LIMIT 1"
            ), {"o": str(order_id)})).first()
            if not already_sched:
                await pe.write_event(
                    db, order_id, pe.PREP_SCHEDULED, actor_type="system",
                    source="system", outlet_id=o.outlet_id,
                    payload={
                        "scheduled_prep_start_at": scheduled_prep_start_at.isoformat(),
                        "latest_safe_start_at": latest_safe_start_at.isoformat(),
                        "mu_ready_s": round(mu_ready),
                        "hold_tolerance_s": hold_tol,
                        "effective_buffer_s": round(effective_buffer_s),
                        # Both inputs to the cap, so which one bound is
                        # recoverable from the log without re-deriving it.
                        "station_buffer_s": station_buffer_s,
                        "trusted_order_count": outlet_state["trusted_order_count"],
                        "reason": "cold_start_jit",
                        # Station dimension (Task 3). order_twin is order-level;
                        # the payload is where the per-station shape is kept so
                        # the stagger gap can be measured before it is modelled.
                        "binding_station": binding_station,
                        "station_load_s": outlet_state.get("_station_load_s", {}),
                        # Explicit, so nobody later mistakes a logged schedule
                        # for something the kitchen was actually told to do.
                        "shadow_mode": True,
                    })

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
