-- 031_scheduled_pickup.sql
--
-- Scheduled pickup: the customer names a future pickup time (same day only),
-- CareVo HOLDS the paid order, and releases it to the restaurant at a computed
-- moment — predicted prep time (mu_ready_s from the existing engine) plus a
-- safety margin — so the food is ready close to when they actually arrive.
--
-- THREE ADDITIVE COLUMNS + ONE INDEX. No existing column is touched, no row is
-- read or written here.
--
-- ============================================================================
-- customer_orders.requested_pickup_at  — the time the CUSTOMER chose
-- ============================================================================
-- NULL for every order placed today and for every ASAP order forever, which is
-- what makes this migration inert until the feature is switched on in the app.
--
-- Stored separately from `release_at` (below) on purpose, and kept even for
-- orders that were never actually held. It is the only record of what the
-- customer ASKED for, and the margin-shrinking dataset is built by joining it
-- against order_outcome.ready_at: "how early or late was the food against the
-- time they picked". A single column that meant both the request and the
-- decision could not answer that question.
--
-- ============================================================================
-- customer_orders.release_at  — WHEN the restaurant is allowed to see it
-- ============================================================================
-- NULL means "not held" and is the ONLY value today's code paths can produce,
-- so every existing order and every ASAP order behaves exactly as before.
--
-- Two different readings of this column, and the difference is load-bearing:
--
--   * the owner queue asks a TIME question — "may the restaurant see it yet" —
--     and uses (release_at IS NULL OR release_at <= now()). Safe to be eager:
--     the worst case is the order appearing a poll-interval early.
--
--   * the pickup-TTL sweeper asks a STATE question — "is this order's pickup
--     window running yet" — and uses (release_at IS NULL) alone. It must NOT
--     use the time form: an order that is due but whose release has not yet
--     executed would become TTL-eligible while still carrying the updated_at
--     stamped at PAYMENT, hours earlier, and the very next sweep would
--     ABANDON it. Clearing release_at at release, in the same breath as
--     advance_status stamps updated_at, is what restarts the 45-minute pickup
--     window at the RELEASE moment rather than at payment.
--
-- Consequence accepted knowingly: while held, an order is exempt from the TTL
-- indefinitely. That is bounded by the feature being same-day only, and a held
-- order has reached no kitchen, so nothing is operationally stuck — it is a
-- paid row waiting for its own release.
--
-- The partial index carries only held orders (a handful at any moment) rather
-- than every order ever placed, because every query that reads this column is
-- looking for exactly that set.
--
-- ============================================================================
-- auto_advance_schedule.kind  — release vs roster-testing
-- ============================================================================
-- auto_advance_schedule (migration 028) is already "one order's next stage and
-- when it is due", durable across a restart. A scheduled release is exactly
-- that shape, so it reuses the table rather than adding a second one.
--
-- The discriminator exists because the two kinds must be processed under
-- OPPOSITE rules:
--
--   * 'roster' rows stay behind AUTO_ADVANCE_ROSTER_ORDERS (off by default,
--     absent from render.yaml, therefore OFF in production) and walk the full
--     RECEIVED -> PREPARING -> READY chain.
--
--   * 'release' rows IGNORE that switch entirely — it is a testing-scoped kill
--     switch and must never gate a real customer feature — and drive exactly
--     ONE advance (PAID -> RECEIVED) before the row is deleted. The real
--     kitchen takes over from there.
--
-- DEFAULT 'roster' so every row that already exists keeps its current meaning
-- without a backfill.
--
-- Additive, idempotent, reversible:
--   ALTER TABLE customer_orders DROP COLUMN requested_pickup_at,
--                               DROP COLUMN release_at;
--   DROP INDEX IF EXISTS customer_orders_held_idx;
--   ALTER TABLE auto_advance_schedule DROP COLUMN kind;
-- restores the schema exactly.

ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS requested_pickup_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS release_at          timestamptz NULL;

CREATE INDEX IF NOT EXISTS customer_orders_held_idx
    ON customer_orders (release_at)
    WHERE release_at IS NOT NULL;

ALTER TABLE auto_advance_schedule
    ADD COLUMN IF NOT EXISTS kind varchar(16) NOT NULL DEFAULT 'roster';

COMMENT ON COLUMN customer_orders.requested_pickup_at IS
    'Pickup time the customer chose (same-day scheduled pickup). NULL for ASAP '
    'orders. Kept even when the order was released immediately: it is the join '
    'key for predicted-vs-actual margin analysis against order_outcome.';

COMMENT ON COLUMN customer_orders.release_at IS
    'When a held order becomes visible to the restaurant. NULL = not held. '
    'Derived as requested_pickup_at - (mu_ready_s + '
    'SCHEDULED_RELEASE_SAFETY_MARGIN_S) and RE-DERIVED as the twin refreshes. '
    'Cleared at release. The owner queue tests (IS NULL OR <= now()); the TTL '
    'sweeper tests (IS NULL) only — see the migration header for why.';

COMMENT ON COLUMN auto_advance_schedule.kind IS
    '''release'' (scheduled pickup, bypasses AUTO_ADVANCE_ROSTER_ORDERS, one '
    'advance then deleted) or ''roster'' (testing auto-progression, gated by '
    'that switch, walks the full stage chain). Default ''roster''.';
