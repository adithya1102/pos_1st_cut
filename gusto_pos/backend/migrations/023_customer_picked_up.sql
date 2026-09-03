-- 023_customer_picked_up.sql
--
-- Give the customer's own "I've picked this up" acknowledgment a real,
-- server-side record, and make GET /customer/orders/{id} able to report the
-- three customer pickup-journey acks (departed / arrived / picked_up).
--
-- WHY NO NEW TABLE OR COLUMN FOR "PICKED UP"
-- ------------------------------------------
-- The ack is recorded as a CUSTOMER_PICKED_UP row in the EXISTING append-only
-- `order_events` log (migration 006), written by the new
-- POST /customer/orders/{id}/picked-up endpoint via the same write_event path
-- that CUSTOMER_DEPARTED and CUSTOMER_ARRIVED already use. So there is nothing
-- to record here in DDL — the event type is just a new string, and the rows are
-- written at runtime.
--
-- An `order_events` row was chosen over a boolean/timestamp column on
-- customer_orders on the merits, not by default:
--   * Consistency — DEPARTED, ARRIVED and staff PICKUP_VERIFIED are all events;
--     the customer ack is the same category of fact and now reads/writes the
--     same way, so OrderOut exposes all three through ONE mechanism.
--   * Correctness — "the customer said they picked it up at time T" is an
--     immutable historical fact. order_events is append-only (a BEFORE
--     UPDATE/DELETE trigger from 006 enforces it); a boolean column could be
--     flipped back, which is the wrong semantics.
--   * Richness — the event carries occurred_at, actor_type=customer,
--     source=tap, feeding the event stream naturally. A bare boolean would not.
-- A column would have been simpler to read (no lookup), but that single upside
-- did not outweigh splitting the read path in two and making an immutable fact
-- mutable.
--
-- WHAT THIS MIGRATION ACTUALLY DOES
-- ---------------------------------
-- Adds a composite index on (order_id, event_type). OrderOut now asks
-- "does this order have a DEPARTED / ARRIVED / PICKED_UP event?" — a per-order,
-- per-type existence check. The existing indexes cover (order_id, seq) and
-- (event_type, occurred_at); neither is ideal for that predicate. This one is,
-- and it also speeds up the _has_event() idempotency check the depart/arrived/
-- picked-up endpoints already run on every call.
--
-- Additive, idempotent, reversible, and it changes NO existing column, index,
-- trigger, or endpoint behaviour. Reverse with: DROP INDEX ix_oe_order_type;
--
-- PRODUCTION NOTE FOR THE REVIEWER: `order_events` grows without bound (it is
-- append-only). A plain CREATE INDEX takes a lock that blocks writes for the
-- build. On a large prod table, run this instead, OUTSIDE a transaction:
--     CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_oe_order_type
--         ON order_events (order_id, event_type);
-- CONCURRENTLY cannot run inside a transaction block, which is why the
-- portable, bootstrap-runnable form below is plain. Same resulting index.

CREATE INDEX IF NOT EXISTS ix_oe_order_type
    ON order_events (order_id, event_type);

COMMENT ON INDEX ix_oe_order_type IS
    'Supports per-order existence checks by event_type: the _has_event() '
    'idempotency guard on the depart/arrived/picked-up endpoints, and the '
    'departed/arrived/picked_up flags GET /customer/orders/{id} now returns '
    '(migration 023). CUSTOMER_PICKED_UP is the customer''s own ack and moves '
    'no order status; staff PICKUP_VERIFIED remains the only real completion.';
