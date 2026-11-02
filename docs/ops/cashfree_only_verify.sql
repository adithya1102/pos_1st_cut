-- ============================================================================
-- CASHFREE_ONLY cutover — VERIFY (read-only)
--
-- Companion to docs/runbooks/CASHFREE_CUTOVER.md. Every statement here is a
-- SELECT. Run against production AFTER the cutover transaction has committed,
-- as part of the "first hour" watch and again at any later health check.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. Migrations 034-038 landed: every column the cutover and the Cashfree
--    hardening fixes depend on actually exists on this database.
-- ----------------------------------------------------------------------------
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE (table_name = 'outlets'
       AND column_name IN ('payment_prepaid_enabled',
                            'payment_pay_at_pickup_enabled',
                            'cashfree_unlocked', 'call_window_s'))
   OR (table_name = 'customer_orders'
       AND column_name IN ('payment_mode', 'contact_phone', 'call_state',
                            'payment_amount_mismatch',
                            'payment_amount_mismatch_at'))
   OR (table_name = 'users' AND column_name = 'is_outlet_owner')
ORDER BY table_name, column_name;


-- ----------------------------------------------------------------------------
-- 2. The cutover outlet's current flags — confirm they match what
--    cashfree_only_cutover.sql set, and have not drifted.
-- ----------------------------------------------------------------------------
SELECT id, name, payment_prepaid_enabled, payment_pay_at_pickup_enabled,
       payment_upi_manual_enabled, cashfree_unlocked
FROM outlets
WHERE id = '<OUTLET_ID>';


-- ----------------------------------------------------------------------------
-- 3. First-hour watch: every order this outlet has taken since the cutover,
--    with the payment path each one actually used. In CASHFREE_ONLY mode
--    every row should show payment_mode = 'PREPAID' — anything else here is
--    either a pre-cutover order still in flight or a sign the switch did not
--    take effect for this outlet.
-- ----------------------------------------------------------------------------
SELECT id, status, payment_status, payment_mode, total_amount,
       payment_amount_mismatch, created_at
FROM customer_orders
WHERE outlet_id = '<OUTLET_ID>'
  AND created_at >= '<CUTOVER_TIMESTAMP_UTC>'
ORDER BY created_at DESC;


-- ----------------------------------------------------------------------------
-- 4. Which gateway actually charged the card/UPI for this outlet's orders
--    since cutover. Every row should read 'cashfree'.
-- ----------------------------------------------------------------------------
SELECT pt.gateway, count(*) AS n
FROM payment_transactions pt
JOIN customer_orders co ON co.id = pt.customer_order_id
WHERE co.outlet_id = '<OUTLET_ID>'
  AND pt.created_at >= '<CUTOVER_TIMESTAMP_UTC>'
GROUP BY pt.gateway;


-- ----------------------------------------------------------------------------
-- 5. Short-payment flags (migration 038). Webhooks reporting PAID for less
--    than total_amount never reach PAID — they surface here instead, for a
--    human to reconcile against the Cashfree dashboard.
-- ----------------------------------------------------------------------------
SELECT id, total_amount, payment_amount_mismatch_at, status, payment_status
FROM customer_orders
WHERE outlet_id = '<OUTLET_ID>'
  AND payment_amount_mismatch = true
ORDER BY payment_amount_mismatch_at DESC;


-- ----------------------------------------------------------------------------
-- 6. Late-payment refund queue: a payment that settled after the order/stock
--    hold already went terminal (ABANDONED). These are flagged, not silently
--    dropped — review and action through the existing refund process.
-- ----------------------------------------------------------------------------
SELECT id, status, refund_required, refund_reason, total_amount, created_at
FROM customer_orders
WHERE outlet_id = '<OUTLET_ID>'
  AND refund_required = true
ORDER BY created_at DESC;
