-- Migration 006: Prediction Engine — event sourcing + prediction tables (§8)
--
-- Additive and idempotent. No existing table is altered destructively; all new
-- columns are nullable or defaulted (NFR-18, no downtime).
--
-- SCHEMA RECONCILIATION (doc §8 says `orders`; this codebase's CareVo order table
-- is `customer_orders`, and a SEPARATE legacy GustoPOS `orders` table also exists).
-- Every order FK below therefore points at customer_orders(id) — NOT orders(id).
-- The doc's §8 intro says "five tables" but lists seven; all seven are created here.
-- is_veg and prep_time_minutes already exist on menu_items (migrations 001/x) and
-- are NOT touched.

-- ---------------------------------------------------------------------------
-- 8.1 order_events — the core append-only asset
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_events (
  id          BIGSERIAL PRIMARY KEY,
  order_id    UUID        NOT NULL REFERENCES customer_orders(id),
  outlet_id   UUID        NOT NULL REFERENCES outlets(id),
  seq         INT         NOT NULL,          -- per-order gap-free sequence
  event_type  TEXT        NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,          -- world time (when it happened)
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- server receipt time
  actor_type  TEXT        NOT NULL,          -- customer | staff | system
  actor_id    UUID,
  source      TEXT        NOT NULL,          -- tap | geofence | system | inferred
  payload     JSONB       NOT NULL DEFAULT '{}',
  UNIQUE (order_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_oe_order      ON order_events (order_id, seq);
CREATE INDEX IF NOT EXISTS ix_oe_outlet_typ ON order_events (outlet_id, event_type, occurred_at);
CREATE INDEX IF NOT EXISTS ix_oe_type_time  ON order_events (event_type, occurred_at);

-- ---------------------------------------------------------------------------
-- 8.2 order_twin — live per-order state (MUTABLE, recomputed on trigger events)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_twin (
  order_id                UUID PRIMARY KEY REFERENCES customer_orders(id),
  version                 INT         NOT NULL DEFAULT 1,
  ready_p50               TIMESTAMPTZ,
  ready_p80               TIMESTAMPTZ,
  ready_sigma_s           INT,
  arrival_p50             TIMESTAMPTZ,
  travel_sigma_s          INT,
  travel_source           TEXT,       -- maps_live | maps_cached | haversine_fallback
  sigma_gap_s             INT,
  depart_window_start     TIMESTAMPTZ,
  depart_window_end       TIMESTAMPTZ,
  promise_start           TIMESTAMPTZ,
  promise_end             TIMESTAMPTZ,
  promise_issued_at       TIMESTAMPTZ,
  promise_revision_count  INT         NOT NULL DEFAULT 0,
  hold_tolerance_s        INT,
  scheduled_prep_start_at TIMESTAMPTZ,
  latest_safe_start_at    TIMESTAMPTZ,
  risk_level              TEXT,       -- low | medium | high
  degraded                BOOLEAN     NOT NULL DEFAULT false,
  inputs                  JSONB       NOT NULL,   -- full feature snapshot
  model_versions          JSONB       NOT NULL,
  last_recomputed_at      TIMESTAMPTZ NOT NULL,
  stale_after             TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_twin_stale ON order_twin (stale_after)
  WHERE promise_start IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 8.3 prediction_log — every prediction ever made (append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prediction_log (
  id             BIGSERIAL PRIMARY KEY,
  order_id       UUID        NOT NULL REFERENCES customer_orders(id),
  outlet_id      UUID        NOT NULL,   -- (doc: no FK on this column)
  predicted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  predictor      TEXT        NOT NULL,   -- kitchen | travel | load | decision | promise
  model_version  TEXT        NOT NULL,
  mu_seconds     INT,
  sigma_seconds  INT,
  features       JSONB       NOT NULL,
  output         JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pl_order ON prediction_log (order_id, predictor, predicted_at);

-- ---------------------------------------------------------------------------
-- 8.4 order_outcome — the training table (one row per terminal order)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_outcome (
  order_id         UUID PRIMARY KEY REFERENCES customer_orders(id),
  outlet_id        UUID        NOT NULL,   -- (doc: no FK on this column)
  accepted_at      TIMESTAMPTZ,
  prep_started_at  TIMESTAMPTZ,
  ready_at         TIMESTAMPTZ,
  departed_at      TIMESTAMPTZ,
  arrived_at       TIMESTAMPTZ,
  collected_at     TIMESTAMPTZ,
  actual_prep_s    INT,
  actual_travel_s  INT,
  actual_hold_s    INT,
  counter_wait_s   INT,
  promise_start    TIMESTAMPTZ,
  promise_end      TIMESTAMPTZ,
  promise_kept     BOOLEAN,
  interval_score   NUMERIC(8,2),
  wait_feedback    TEXT,        -- 0 | 1-3 | 3-5 | 5+
  kitchen_trust    NUMERIC(3,2) NOT NULL,
  travel_trust     NUMERIC(3,2) NOT NULL,
  customer_trust   NUMERIC(3,2) NOT NULL,
  trust_failures   JSONB       NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS ix_oo_train ON order_outcome (outlet_id, kitchen_trust, ready_at);

-- ---------------------------------------------------------------------------
-- 8.5 travel_cache — Maps API cost control
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS travel_cache (
  origin_geohash6 TEXT        NOT NULL,
  outlet_id       UUID        NOT NULL,
  mode            TEXT        NOT NULL,
  quarter_hour    SMALLINT    NOT NULL,   -- 0..671 (quarter-hour of week)
  eta_seconds     INT         NOT NULL,
  sample_count    INT         NOT NULL DEFAULT 1,
  refreshed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (origin_geohash6, outlet_id, mode, quarter_hour)
);

-- ---------------------------------------------------------------------------
-- 8.6 travel_bias — learned Maps correction
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS travel_bias (
  outlet_id        UUID         NOT NULL,
  mode             TEXT         NOT NULL,
  daypart          TEXT         NOT NULL,  -- morning | lunch | afternoon | evening | night
  bias_factor      NUMERIC(4,3) NOT NULL DEFAULT 1.000,
  residual_sigma_s INT          NOT NULL DEFAULT 240,
  sample_count     INT          NOT NULL DEFAULT 0,
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  PRIMARY KEY (outlet_id, mode, daypart)
);

-- ---------------------------------------------------------------------------
-- 8.7 outlet_reliability — per-outlet quality summary (drives graduation)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outlet_reliability (
  outlet_id             UUID PRIMARY KEY REFERENCES outlets(id),
  trusted_order_count   INT         NOT NULL DEFAULT 0,
  median_prep_s         INT,
  prep_residual_sigma_s INT,
  interval_score_p50    NUMERIC(8,2),
  fulfillment_rate      NUMERIC(4,3),
  median_window_width_s INT,
  tap_discipline        NUMERIC(3,2),  -- fraction of orders with all 3 taps
  shadow_mode           BOOLEAN     NOT NULL DEFAULT true,
  graduated_at          TIMESTAMPTZ,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 8.8 Column additions (nullable/defaulted — NFR-18). is_veg / prep_time_minutes
-- already exist on menu_items and are intentionally not re-added.
-- ---------------------------------------------------------------------------
ALTER TABLE menu_items
  ADD COLUMN IF NOT EXISTS station                TEXT    DEFAULT 'other',
  ADD COLUMN IF NOT EXISTS base_prep_seconds      INT,
  ADD COLUMN IF NOT EXISTS occupancy_seconds      INT,
  ADD COLUMN IF NOT EXISTS hold_tolerance_seconds INT,
  ADD COLUMN IF NOT EXISTS is_batchable           BOOLEAN DEFAULT false;

-- doc §8.8 "orders" additions -> customer_orders (the CareVo order table)
ALTER TABLE customer_orders
  ADD COLUMN IF NOT EXISTS transport_mode TEXT,
  ADD COLUMN IF NOT EXISTS origin_lat     NUMERIC,
  ADD COLUMN IF NOT EXISTS origin_lng     NUMERIC,
  ADD COLUMN IF NOT EXISTS origin_source  TEXT;

-- ---------------------------------------------------------------------------
-- FR-E3 / NFR-9 — DB-level immutability for the append-only assets.
--
-- Mechanism: a BEFORE UPDATE/DELETE/TRUNCATE trigger that raises. Privilege
-- REVOKE is NOT used: this deployment connects as the table-owning Neon role,
-- and an owner bypasses table GRANTs — so REVOKE would be a no-op here. A
-- trigger fires for every role (owner included) and is the reliable choice.
-- Applied to order_events (the FR-E3 event log) and prediction_log (§8.3
-- append-only). INSERT remains allowed.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION carevo_reject_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'append-only table %: % is not permitted', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER order_events_immutable
  BEFORE UPDATE OR DELETE ON order_events
  FOR EACH ROW EXECUTE FUNCTION carevo_reject_mutation();
CREATE OR REPLACE TRIGGER order_events_no_truncate
  BEFORE TRUNCATE ON order_events
  FOR EACH STATEMENT EXECUTE FUNCTION carevo_reject_mutation();

CREATE OR REPLACE TRIGGER prediction_log_immutable
  BEFORE UPDATE OR DELETE ON prediction_log
  FOR EACH ROW EXECUTE FUNCTION carevo_reject_mutation();
CREATE OR REPLACE TRIGGER prediction_log_no_truncate
  BEFORE TRUNCATE ON prediction_log
  FOR EACH STATEMENT EXECUTE FUNCTION carevo_reject_mutation();
