-- Migration 014: push notification tokens + delivery log
--
-- Additive and idempotent. Two changes:
--   1. customers.fcm_token  — where to send
--   2. push_notifications   — what was sent, and the once-only guard
--
-- NOTE ON SCOPE: no scheduling state lives here. The nudge jobs are triggered
-- externally (see PushService.run_* + the admin endpoints); this table is what
-- makes them idempotent, so a trigger firing twice cannot double-notify.

-- 1. Device token ------------------------------------------------------------
-- Nullable: a customer has no token until the app registers one, and tokens are
-- revoked/rotated by FCM, so NULL is a normal ongoing state, not just an
-- initial one. Long varchar — FCM registration tokens are ~163 chars today but
-- Google documents no fixed maximum.
ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS fcm_token varchar(512);

-- Updated whenever the app re-registers, so a stale token can be spotted.
ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS fcm_token_updated_at timestamptz;

-- Partial index: sends only ever scan customers that HAVE a token.
CREATE INDEX IF NOT EXISTS idx_customers_fcm_token
    ON customers (id) WHERE fcm_token IS NOT NULL;

-- 2. Delivery log -------------------------------------------------------------
-- Every push attempt, successful or not. Exists for two reasons:
--   * once-only nudges — "has this customer already had a REENGAGEMENT?" is a
--     query against this table, not scheduler state that a restart would lose
--   * an audit trail, matching how admin_audit_logs backs admin actions
CREATE TABLE IF NOT EXISTS push_notifications (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    -- ORDER_STATUS | REENGAGEMENT | DISH_SUGGESTION
    kind         varchar(24) NOT NULL,
    title        varchar(120) NOT NULL,
    body         varchar(400) NOT NULL,
    -- Set for ORDER_STATUS so a per-order push is traceable to its order.
    order_id     uuid REFERENCES customer_orders(id) ON DELETE SET NULL,
    -- sent = FCM accepted it; skipped = no token / push disabled;
    -- failed = FCM rejected it. A row is written either way, so "nothing
    -- happened" and "we never tried" are distinguishable after the fact.
    status       varchar(12) NOT NULL DEFAULT 'sent',
    detail       text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT push_kind_valid CHECK (
        kind IN ('ORDER_STATUS', 'REENGAGEMENT', 'DISH_SUGGESTION')),
    CONSTRAINT push_status_valid CHECK (status IN ('sent', 'skipped', 'failed'))
);

-- The once-only lookup: "most recent nudge of kind K for customer C".
CREATE INDEX IF NOT EXISTS idx_push_customer_kind
    ON push_notifications (customer_id, kind, created_at DESC);

-- Order-status pushes must not repeat for the same order+status if a
-- transition is re-broadcast (mark_paid is idempotent and can re-run).
-- Partial unique index so nudge rows, which have no order_id, are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS idx_push_one_per_order_status
    ON push_notifications (order_id, title)
    WHERE kind = 'ORDER_STATUS' AND order_id IS NOT NULL AND status = 'sent';
