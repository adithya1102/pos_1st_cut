-- 024_outlet_hours.sql
--
-- Restaurant operating hours + a manual "temporarily closed" toggle, so a
-- customer cannot place an order a kitchen has no time to fulfil before close,
-- and an owner can shut early on demand.
--
-- THREE ADDITIVE COLUMNS ON `outlets`. No existing column is touched.
--
--   opens_at, closes_at  — TIME (time-of-day), NOT timestamptz. These are a
--     DAILY RECURRING schedule ("we open at 09:00, close at 22:00"), not
--     per-date hours. Nullable: every existing outlet has no hours on record,
--     and NULL is read as "no schedule set → always open", so this migration is
--     inert for current outlets until an owner enters hours. A per-day-of-week
--     schedule was deliberately NOT built: the only client scaffold that exists
--     (customer_app Outlet.opening_time/closing_time) is a single pair, and
--     nothing in the schema implies weekday/weekend variation. If that becomes
--     needed it is a separate table (outlet_hours(outlet_id, dow, opens, closes)),
--     not a widening of these two columns.
--
--   is_manually_closed — BOOLEAN NOT NULL DEFAULT false. The owner's on-demand
--     "closed now" switch, INDEPENDENT of the scheduled hours and independent of
--     is_visible (migration 011). is_visible hides the storefront from the list;
--     this one keeps it listed but refuses new orders with a "temporarily
--     closed" reason. Default false = every existing outlet keeps accepting
--     orders exactly as before.
--
-- The evaluation of these (open / closing-soon within ORDER_CUTOFF_MINUTES /
-- closed) lives in application code (CarevoService.outlet_availability), not in
-- the DB, because it needs the outlet's local wall-clock (IST) and a tunable
-- cutoff — logic, not schema. This migration only stores the inputs.
--
-- Additive, idempotent, reversible:
--   ALTER TABLE outlets DROP COLUMN opens_at, DROP COLUMN closes_at,
--                       DROP COLUMN is_manually_closed;
-- restores the schema exactly. No order row is read or written here.

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS opens_at  time NULL,
    ADD COLUMN IF NOT EXISTS closes_at time NULL,
    ADD COLUMN IF NOT EXISTS is_manually_closed boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN outlets.opens_at IS
    'Daily opening time-of-day (recurring, not per-date). NULL = no schedule '
    'set, treated as always open. See CarevoService.outlet_availability.';
COMMENT ON COLUMN outlets.closes_at IS
    'Daily closing time-of-day. NULL = no schedule set. New orders are refused '
    'within ORDER_CUTOFF_MINUTES of this, and outside opens_at..closes_at.';
COMMENT ON COLUMN outlets.is_manually_closed IS
    'Owner''s on-demand "temporarily closed" switch. Independent of the '
    'schedule and of is_visible: the outlet stays listed but refuses new '
    'orders. Default false.';
