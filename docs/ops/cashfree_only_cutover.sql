-- ============================================================================
-- CASHFREE_ONLY cutover — ONE outlet, ONE transaction
--
-- Companion to docs/runbooks/CASHFREE_CUTOVER.md. Run this ONLY after:
--   1. docs/ops/trial_residue_check.sql has been run against a copy of
--      production and the owner has decided KEEP/ARCHIVE for every row it
--      found (that script is read-only and does not need to run again here);
--   2. the rehearsal on a FRESH copy of production (never the old
--      youpi-trial copy) has completed cleanly, per the runbook;
--   3. the owner's own Cashfree sandbox keys have been smoke-tested per the
--      runbook's sandbox checklist.
--
-- WHAT THIS DOES
-- --------------
-- Flips exactly two columns on exactly one outlet, both additive columns
-- from migrations 034 and 035:
--   payment_prepaid_enabled = true   (034 — the owner offers online payment)
--   cashfree_unlocked       = true   (035 — CareVo permits it for this outlet)
--
-- Both are already read together by CarevoService.payment_methods_for
-- (gusto_pos/backend/app/modules/carevo_customer/service.py, ~line 1263-1294):
-- PREPAID is only ever offered when prepaid_on AND cashfree_unlocked AND the
-- gateway reports is_live. This statement supplies the first two; the third
-- comes from PAYMENT_GATEWAY=cashfree + CASHFREE_ONLY=true on the Render
-- service (see the runbook), not from this database.
--
-- Replace <OUTLET_ID> below with the real outlet UUID before running. This
-- file intentionally does not default it to anything — a cutover run with a
-- placeholder outlet id must fail loudly, not silently touch zero rows.
--
-- SAFE TO RE-RUN: both columns are already idempotent booleans; running this
-- twice against the same outlet changes nothing the second time.
-- ============================================================================

BEGIN;

-- Snapshot BEFORE, so the operator has the exact prior values on hand if
-- docs/ops/cashfree_only_cutover_rollback.sql is needed later. Read this
-- output and keep it with the runbook's sign-off record for this outlet.
SELECT id, name, payment_prepaid_enabled, payment_pay_at_pickup_enabled,
       payment_upi_manual_enabled, cashfree_unlocked
FROM outlets
WHERE id = '<OUTLET_ID>';

UPDATE outlets
   SET payment_prepaid_enabled = true,
       cashfree_unlocked       = true
 WHERE id = '<OUTLET_ID>';

-- Snapshot AFTER, in the same transaction, so the operator confirms the
-- write landed before committing.
SELECT id, name, payment_prepaid_enabled, payment_pay_at_pickup_enabled,
       payment_upi_manual_enabled, cashfree_unlocked
FROM outlets
WHERE id = '<OUTLET_ID>';

-- Review both SELECTs above. If the AFTER row is not exactly
-- (payment_prepaid_enabled=true, cashfree_unlocked=true) for the intended
-- outlet, ROLLBACK instead of COMMIT.
COMMIT;
