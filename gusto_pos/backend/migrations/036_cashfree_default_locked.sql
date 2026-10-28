-- 036_cashfree_default_locked.sql
--
-- Flip the DEFAULT on outlets.cashfree_unlocked from true to false, so a
-- restaurant that joins from now on has online payment INVISIBLE until CareVo
-- activates it.
--
-- ============================================================================
-- WHAT THIS DOES AND DOES NOT DO
-- ============================================================================
-- ALTER COLUMN ... SET DEFAULT changes only what a FUTURE insert gets when it
-- does not name the column. It does NOT rewrite rows and does NOT touch the
-- existing ones: every outlet already on the platform keeps cashfree_unlocked
-- as it stands, which for all of them is true (035 added the column with that
-- default and nothing has changed it).
--
-- That asymmetry is the entire point. Existing restaurants are mid-trade with
-- Cashfree working; new ones should not be offered a payment method whose
-- onboarding has not happened. A migration that backfilled false would turn
-- online payment off under live restaurants, which is the opposite of what is
-- wanted.
--
-- ============================================================================
-- WHY A DEFAULT AND NOT APPLICATION CODE
-- ============================================================================
-- Because the inserts are not all in one place. Outlets are created by
-- CarevoService.register_owner, by the admin dashboard, by reset_db.py and by
-- hand in SQL during onboarding — and none of them names cashfree_unlocked.
-- A column default is the only mechanism every one of those paths goes through
-- without being edited.
--
-- ============================================================================
-- THE VISIBLE CONSEQUENCE
-- ============================================================================
-- A new outlet now has (prepaid=true, pay_at_pickup=false, upi_manual=false,
-- cashfree_unlocked=false). payment_methods_for therefore resolves to [] —
-- the owner's prepaid flag is on but permission is absent — so the restaurant
-- can take NO orders until somebody acts:
--
--   * an admin unlocks Cashfree (PATCH /admin/outlets/{id}/payment-methods
--     with cashfree_unlocked=true), or
--   * the owner turns on pay-at-pickup or direct UPI in their own settings.
--
-- That is deliberate and is not a soft failure: the outlet is also
-- is_visible=false until an admin approves it, so a half-onboarded restaurant
-- is not reachable by customers in the first place. The empty list is what the
-- owner app renders as "you have not chosen how to get paid yet".
--
-- ck_outlets_payment_method_any is unaffected — it constrains the three method
-- flags, and prepaid stays true. Permission and preference are different
-- columns precisely so this can be the case.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   ALTER TABLE outlets ALTER COLUMN cashfree_unlocked SET DEFAULT true;
--
-- Clean at any time and affects only future inserts, exactly like this file.
-- It does not restore anything, because nothing was destroyed.

ALTER TABLE outlets ALTER COLUMN cashfree_unlocked SET DEFAULT false;

COMMENT ON COLUMN outlets.cashfree_unlocked IS
    'PLATFORM permission to offer online payment, distinct from the owner''s '
    'own payment_prepaid_enabled preference. DEFAULT false since migration '
    '036: a restaurant joining now has Cashfree invisible until CareVo '
    'activates it. Outlets created before 036 kept true and are unaffected — '
    'the default was changed, no row was rewritten. Only an admin may change '
    'it; the owner route reads it to decide whether to render the Cashfree '
    'control at all.';
