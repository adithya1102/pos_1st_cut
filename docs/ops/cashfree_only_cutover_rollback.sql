-- ============================================================================
-- CASHFREE_ONLY cutover — ROLLBACK for ONE outlet
--
-- Exact inverse of docs/ops/cashfree_only_cutover.sql's write. Run this if
-- the first hour of watching the cutover outlet (see the runbook's "first
-- hour" checklist) turns up a problem that needs the outlet pulled back out
-- of Cashfree-only operation immediately.
--
-- WHAT THIS DOES
-- --------------
-- cashfree_unlocked = false   re-locks Cashfree for this outlet. This alone
-- is sufficient: CarevoService.payment_methods_for's PREPAID branch requires
-- prepaid_on AND cashfree_unlocked AND gateway_can_charge() together
-- (service.py ~line 1281-1294), so clearing cashfree_unlocked removes PREPAID
-- from this outlet's methods regardless of what payment_prepaid_enabled says.
--
-- payment_prepaid_enabled is LEFT AS-IS (true), deliberately NOT reset to its
-- pre-cutover value. It was already true for every pre-036 outlet before this
-- cutover touched anything (migration 034's default), and leaving it true is
-- harmless once cashfree_unlocked is false — the owner's "I want online
-- payment" preference is not itself a security boundary, CareVo's permission
-- bit is. If this outlet's payment_prepaid_enabled was NOT true before the
-- forward script ran (check the "Snapshot BEFORE" output you kept from that
-- run), restore it by hand with the same UPDATE/transaction shape below.
--
-- Replace <OUTLET_ID> before running — same rule as the forward script: no
-- default, so a placeholder cannot silently touch nothing.
-- ============================================================================

BEGIN;

SELECT id, name, payment_prepaid_enabled, payment_pay_at_pickup_enabled,
       payment_upi_manual_enabled, cashfree_unlocked
FROM outlets
WHERE id = '<OUTLET_ID>';

UPDATE outlets
   SET cashfree_unlocked = false
 WHERE id = '<OUTLET_ID>';

SELECT id, name, payment_prepaid_enabled, payment_pay_at_pickup_enabled,
       payment_upi_manual_enabled, cashfree_unlocked
FROM outlets
WHERE id = '<OUTLET_ID>';

-- Review both SELECTs above. If the AFTER row does not show
-- cashfree_unlocked=false for the intended outlet, ROLLBACK instead of COMMIT.
COMMIT;
