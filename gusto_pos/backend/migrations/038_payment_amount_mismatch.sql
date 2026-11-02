-- 038_payment_amount_mismatch.sql
--
-- Two additive columns on customer_orders so mark_paid can flag a webhook
-- that reports PAID for less than the order's total, without reusing
-- refund_required (whose established meaning elsewhere is "we HELD money
-- and now owe it back" — this is the opposite case, money that never
-- reached full payment and so was never marked PAID at all).
--
-- ============================================================================
-- WHAT THIS DOES AND DOES NOT DO
-- ============================================================================
-- ADD COLUMN ... DEFAULT false/NULL. Every existing row gets the default; no
-- existing row is UPDATEd to a different value, and no existing query that
-- does not name these columns changes behaviour.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   ALTER TABLE customer_orders
--       DROP COLUMN IF EXISTS payment_amount_mismatch,
--       DROP COLUMN IF EXISTS payment_amount_mismatch_at;
--
-- Clean at any time: nothing else reads or writes these two columns.

ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS payment_amount_mismatch    boolean     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS payment_amount_mismatch_at timestamptz NULL;

COMMENT ON COLUMN customer_orders.payment_amount_mismatch IS
    'Set by CarevoService.mark_paid when a gateway webhook reports PAID for '
    'less than total_amount. The order is NOT marked PAID and mints no '
    'pickup code — this only records that a short payment arrived, for a '
    'human to reconcile against the gateway dashboard.';
