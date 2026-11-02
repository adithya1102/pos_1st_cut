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


-- ----------------------------------------------------------------------------
-- 7. DAILY REFUND-DUE CHECK. Run once a day against the whole platform (no
--    outlet_id filter — this is the admin's cross-outlet queue), or hit the
--    equivalent live route: GET /api/v1/admin/orders/refund-due
--    (carevo_admin/controller.py -> AdminService.list_refund_due,
--    carevo_admin/service.py ~line 1512). Nothing PUSHES this list to anyone
--    — there is no admin push/email notification on refund_required being
--    set (confirmed by code review; see REFUND_REQUIRED_FLAGGED in the app
--    log as the only automatic signal) — so this query (or the route) must
--    be run on a schedule, not waited for.
-- ----------------------------------------------------------------------------
SELECT id, outlet_id, status, refund_required, refund_reason, total_amount,
       refund_flagged_at
FROM customer_orders
WHERE refund_required = true
ORDER BY refund_flagged_at DESC
LIMIT 500;


-- ----------------------------------------------------------------------------
-- 8. RECONCILIATION: rows that are CANCELLED but still carry a presentable
--    pickup code, or are PAID with refund_required — both are inconsistent
--    states a cancelled/refund-due order must never be in (Task 1c closed
--    the pickup_code half of this going forward; this query catches any
--    pre-existing row, or a regression, either way).
-- ----------------------------------------------------------------------------
SELECT id, outlet_id, status, payment_status, pickup_code, refund_required,
       refund_reason, created_at
FROM customer_orders
WHERE (status = 'CANCELLED' AND pickup_code IS NOT NULL)
   OR (payment_status = 'PAID' AND refund_required = true)
ORDER BY created_at DESC;
