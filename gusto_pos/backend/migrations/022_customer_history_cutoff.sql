-- 022_customer_history_cutoff.sql
--
-- Hide a customer's older orders from THEIR OWN history view, without deleting
-- anything.
--
-- Motivation: three test accounts had accumulated 61 orders between them,
-- mostly abandoned checkouts (CREATED / payment PENDING) left over from
-- development. Deleting them was attempted and correctly refused by the
-- database — `order_events` and `prediction_log` carry BEFORE DELETE
-- immutability triggers, because the prediction engine is event-sourced and
-- those rows ARE the record. Hiding is therefore not a soft-delete compromise;
-- it is the only option the schema permits, and the right one.
--
-- WHY A CUTOFF ON `customers`, NOT A FLAG ON `customer_orders`:
--
--   * It writes 3 rows instead of 61, and stays 3 however many orders exist.
--   * The accounts are STILL IN USE for testing. A per-order flag would need
--     re-applying after every new test order or the history refills; a cutoff
--     means "everything before this instant is hidden, everything after shows
--     normally" — which is the actual intent.
--   * It mirrors CarevoService.RENAME_CUTOFF, which already does exactly this
--     shape for owner_app's queue (hide orders predating an outlet's rename).
--     One pattern for "hide history before an instant" rather than two.
--
-- The trade-off, recorded so it is not discovered later: this is strictly
-- chronological. It CANNOT hide one order while leaving an older one visible.
-- If per-order granularity is ever needed, this column does not provide it and
-- a flag on customer_orders would have to be added alongside.
--
-- NULL means "no cutoff, show everything", which is every existing row — so
-- this is inert until a value is set. Nullable rather than NOT NULL DEFAULT
-- because "no cutoff" is genuinely the absence of a value, not a sentinel date;
-- the alternative would be picking an epoch and asking every reader to know it.
--
-- Additive, idempotent, reversible: `UPDATE customers SET history_cutoff_at =
-- NULL` restores every hidden order to view instantly, and dropping the column
-- returns the schema exactly to its prior state. No order row is read or
-- written by this migration.

ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS history_cutoff_at timestamptz NULL;

COMMENT ON COLUMN customers.history_cutoff_at IS
    'Orders created before this instant are hidden from this customer''s own '
    'order history (GET /customer/orders). NULL = show all. Never affects '
    'owner_app, the admin order log, or the rows themselves.';

-- Deliberately NO index. The column is read once per history request, already
-- filtered by customer_id (which is indexed), and is NULL for essentially every
-- row — an index would be dead weight on a table this size.
