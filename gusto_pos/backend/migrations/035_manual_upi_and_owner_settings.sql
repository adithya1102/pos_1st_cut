-- 035_manual_upi_and_owner_settings.sql
--
-- Two things that belong together because one is the reason for the other:
--
--   (a) DIRECT UPI (payment_mode 'UPI_MANUAL') — the customer pays the
--       restaurant's own VPA from their own UPI app, taps "I've paid", and the
--       restaurant checks its UPI app before accepting. No gateway, no
--       settlement account, no commission.
--   (b) OWNER SELF-SERVE payment settings — because (a) only works if the
--       restaurant can enter its own VPA, and because an owner who cannot
--       switch Cashfree off is not really being offered an alternative.
--
-- ADDITIVE ONLY, with ONE exception that is called out loudly below:
-- ck_outlets_payment_method_any is REPLACED, because the invariant it encodes
-- ("an outlet must accept at least one payment method") has to grow a third
-- method or it would forbid the very configuration this migration enables.
-- Nothing else is altered or dropped; no row is read or written.
--
-- ============================================================================
-- WHY 'UPI_MANUAL' WAS ALREADY IN THE CHECK
-- ============================================================================
-- Migration 034 put 'UPI_MANUAL' into ck_customer_orders_payment_mode as a
-- RESERVED value that nothing wrote, specifically so that enabling it later
-- would be a code change rather than a constraint swap on a live table. This
-- is that later. The CHECK is untouched here — it already permits the value.
--
-- ============================================================================
-- outlets.cashfree_unlocked
-- ============================================================================
-- DEFAULT true, so every existing outlet keeps Cashfree exactly as it is.
--
-- This is a PLATFORM lock, not an owner preference, and the two must not be
-- confused: payment_prepaid_enabled is the owner saying "I want to offer
-- online payment", cashfree_unlocked is CareVo saying "you may". An outlet
-- whose gateway onboarding is incomplete, or whose account is under review,
-- has cashfree_unlocked=false and the owner's own toggle is then shown locked
-- rather than silently ignored — the owner app reads this to render the
-- "Currently unavailable for your restaurant" state instead of a switch that
-- flips back.
--
-- Only an admin can change it (PATCH /admin/outlets/{id}/payment-methods).
-- The owner-facing route can read it but never write it.
--
-- ============================================================================
-- outlets.upi_vpa / upi_payee_name / upi_attested_at
-- ============================================================================
-- ck_outlets_upi_vpa_shape is a SHAPE check, not a validity check, and the
-- difference matters: no regex can tell you whether a VPA will actually
-- receive money. It rejects the typos that are certainly wrong (no @, spaces,
-- an empty handle) and nothing more.
--
-- ATTESTATION is what stands in for validation. upi_attested_at is stamped
-- only when the owner confirms they sent themselves Rs 1 through this exact
-- VPA and received it, which is the only test that proves the thing we
-- actually care about: that money arriving at this string reaches THEM.
--
-- ck_outlets_upi_manual_requires_vpa makes that a database fact rather than an
-- application convention: the flag cannot be on without all three of VPA,
-- payee name and attestation. So a direct-UPI order can never be placed
-- against an outlet that has not proven it can be paid — not by a race, not by
-- a stale client, not by a hand-written UPDATE that forgot a column.
--
-- CHANGING THE VPA CLEARS THE ATTESTATION. That is enforced in the service
-- (set_owner_payment_methods), not here, because it is a transition rule
-- rather than a state invariant — but the invariant above is what makes it
-- safe: clearing upi_attested_at necessarily forces the flag off too.
--
-- ============================================================================
-- customer_orders.payment_claimed_at
-- ============================================================================
-- When the customer said they had paid. NOT when they paid, and the column is
-- named for what it is: an unverified assertion by one party.
--
-- It is the gate on accepting a direct-UPI order (the restaurant must not be
-- offered Accept before the customer claims to have sent anything) and it
-- starts the acceptance clock. The money is confirmed by a human looking at
-- their own UPI app, and that confirmation is the Accept tap.
--
-- ============================================================================
-- customer_orders.manual_refund_due / manual_refund_reason
-- ============================================================================
-- SEPARATE FROM refund_required (032), deliberately, and not a duplicate of
-- it. refund_required means "money came in through the GATEWAY and has to go
-- back out through it" and feeds the admin refund queue at
-- /admin/orders/refund-due. A direct-UPI refund never touches that queue: the
-- money went customer -> restaurant with CareVo not in the path, so CareVo
-- cannot refund it and must not list it as though it could. The restaurant
-- pays the customer back itself, from the same UPI app the money landed in.
--
-- Two columns rather than one so the owner app can say WHY, and so a future
-- reader can tell a "we cannot make your order" refund from any other.
--
-- ============================================================================
-- customers.false_claim_count
-- ============================================================================
-- Times a restaurant said the money never arrived after this customer claimed
-- it had. At 2 direct-UPI stops being offered to them (the resolver withholds
-- it); prepaid and pay-at-pickup are unaffected.
--
-- DISTINCT from no_show_count (034). A no-show wasted food; a false claim
-- asserted a payment that did not exist. They are different kinds of bad
-- behaviour with different thresholds, and collapsing them would make the
-- first offence of either look like the second of one.
--
-- NOT reset automatically, same reasoning as no_show_count: clearing it is an
-- explicit admin act.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- Additive except for the one replaced CHECK, so rollback restores the prior
-- invariant explicitly rather than just dropping things:
--
--   ALTER TABLE outlets
--       DROP CONSTRAINT IF EXISTS ck_outlets_payment_method_any,
--       DROP CONSTRAINT IF EXISTS ck_outlets_upi_vpa_shape,
--       DROP CONSTRAINT IF EXISTS ck_outlets_upi_manual_requires_vpa,
--       DROP CONSTRAINT IF EXISTS fk_outlets_payment_settings_updated_by,
--       DROP COLUMN payment_upi_manual_enabled, DROP COLUMN upi_vpa,
--       DROP COLUMN upi_payee_name, DROP COLUMN upi_attested_at,
--       DROP COLUMN cashfree_unlocked,
--       DROP COLUMN payment_settings_updated_at,
--       DROP COLUMN payment_settings_updated_by;
--   ALTER TABLE outlets ADD CONSTRAINT ck_outlets_payment_method_any
--       CHECK (payment_prepaid_enabled OR payment_pay_at_pickup_enabled);
--   DROP INDEX IF EXISTS customer_orders_manual_refund_due_idx;
--   ALTER TABLE customer_orders
--       DROP COLUMN payment_claimed_at, DROP COLUMN manual_refund_due,
--       DROP COLUMN manual_refund_reason;
--   ALTER TABLE customers DROP COLUMN false_claim_count;
--
-- !! ROLL BACK THE COLUMNS ONLY WHILE NO OUTLET HAS UPI_MANUAL ON. Restoring
-- !! the two-flag CHECK against an outlet whose only enabled method is
-- !! upi_manual fails, and should: that outlet would be left unable to take
-- !! any order at all. Turn those outlets back to prepaid or pay-at-pickup
-- !! first. It also stops being clean once a manual refund has been recorded,
-- !! since manual_refund_reason is then the only record of why.
--
-- ============================================================================
-- NOT ORM-MAPPED
-- ============================================================================
-- Same discipline as 031 and 034: every column here is read and written with
-- raw text() SQL. A mapped column goes into every SELECT SQLAlchemy emits
-- against the table, so shipping code to an environment where this has not run
-- would break every query against outlets rather than only the new one.

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS payment_upi_manual_enabled  boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS upi_vpa                     text        NULL,
    ADD COLUMN IF NOT EXISTS upi_payee_name              text        NULL,
    ADD COLUMN IF NOT EXISTS upi_attested_at             timestamptz NULL,
    ADD COLUMN IF NOT EXISTS cashfree_unlocked           boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS payment_settings_updated_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS payment_settings_updated_by uuid        NULL;

-- Who last changed the settings. ON DELETE SET NULL rather than CASCADE:
-- removing a staff account must not delete the outlet's configuration.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'fk_outlets_payment_settings_updated_by'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT fk_outlets_payment_settings_updated_by
            FOREIGN KEY (payment_settings_updated_by)
            REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

-- A SHAPE check. It cannot tell you whether a VPA receives money — that is
-- what the attestation below is for — only that it is not one of the typos
-- that are certainly wrong.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_outlets_upi_vpa_shape'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT ck_outlets_upi_vpa_shape
            -- {2,255}, NOT {2,256}. PostgreSQL's regex engine caps bounded
            -- repetition counts at 255 and rejects anything higher with
            -- "invalid regular expression: invalid repetition count(s)" — and
            -- it does so when the pattern is EVALUATED, not when the
            -- constraint is created, so a 256 here would have created cleanly
            -- against an empty table and then failed on the first real UPI ID
            -- anybody saved. One character shorter than specified, and the
            -- limit is well past any real VPA (handles are a dozen or so
            -- characters).
            CHECK (upi_vpa IS NULL
                   OR upi_vpa ~ '^[A-Za-z0-9._-]{2,255}@[A-Za-z]{2,64}$');
    END IF;
END $$;

-- THE INVARIANT THAT MATTERS: direct UPI cannot be on until the outlet has
-- proven it can be paid. Enforced here so no race, stale client or
-- hand-written UPDATE can place an order against an unattested VPA.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_outlets_upi_manual_requires_vpa'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT ck_outlets_upi_manual_requires_vpa
            CHECK (NOT payment_upi_manual_enabled
                   OR (upi_vpa IS NOT NULL
                       AND upi_payee_name IS NOT NULL
                       AND upi_attested_at IS NOT NULL));
    END IF;
END $$;

-- ============================================================================
-- THE ONE NON-ADDITIVE STATEMENT IN THIS FILE
-- ============================================================================
-- ck_outlets_payment_method_any (034) reads
--     CHECK (payment_prepaid_enabled OR payment_pay_at_pickup_enabled)
-- which would forbid an outlet whose only method is direct UPI — the exact
-- configuration this migration exists to allow. It is replaced rather than
-- added alongside, because two overlapping "at least one method" constraints
-- would disagree and the stricter one would always win.
--
-- DROP-then-ADD is safe to run against a live table here: both forms are
-- satisfied by every existing row (every outlet has payment_prepaid_enabled
-- true by default), so there is no instant at which a valid row becomes
-- invalid. The window between the two statements is inside one transaction.
ALTER TABLE outlets DROP CONSTRAINT IF EXISTS ck_outlets_payment_method_any;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_outlets_payment_method_any'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT ck_outlets_payment_method_any
            CHECK (payment_prepaid_enabled
                   OR payment_pay_at_pickup_enabled
                   OR payment_upi_manual_enabled);
    END IF;
END $$;

ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS payment_claimed_at   timestamptz NULL,
    ADD COLUMN IF NOT EXISTS manual_refund_due    boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS manual_refund_reason text        NULL;

ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS false_claim_count integer NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customers_false_claim_count'
    ) THEN
        ALTER TABLE customers
            ADD CONSTRAINT ck_customers_false_claim_count
            CHECK (false_claim_count >= 0);
    END IF;
END $$;

-- The restaurant's own refund worklist. Partial and tiny, like the gateway
-- refund index next to it — and deliberately a SEPARATE index, because the two
-- queues have different owners: this one is the restaurant's to settle, and
-- customer_orders_refund_due_idx is CareVo's.
CREATE INDEX IF NOT EXISTS customer_orders_manual_refund_due_idx
    ON customer_orders (updated_at)
    WHERE manual_refund_due;

COMMENT ON COLUMN outlets.cashfree_unlocked IS
    'PLATFORM permission to offer online payment, distinct from the owner''s '
    'own payment_prepaid_enabled preference. true for every existing outlet. '
    'Only an admin may change it; the owner route reads it to render the '
    'toggle as locked rather than silently refusing the flip.';

COMMENT ON COLUMN outlets.upi_attested_at IS
    'When the owner confirmed they sent themselves Rs 1 through this exact VPA '
    'and received it. Stands in for validation, because no regex can tell you '
    'whether a VPA reaches the person who typed it. CLEARED whenever upi_vpa '
    'changes, which by ck_outlets_upi_manual_requires_vpa also forces '
    'payment_upi_manual_enabled off until it is re-attested.';

COMMENT ON COLUMN customer_orders.payment_claimed_at IS
    'When the CUSTOMER said they had paid — an unverified assertion by one '
    'party, which is why the column is not called paid_at. It gates the Accept '
    'tap and starts the acceptance clock; the money itself is confirmed by a '
    'human reading their own UPI app, and that confirmation IS the Accept.';

COMMENT ON COLUMN customer_orders.manual_refund_due IS
    'The RESTAURANT owes this customer money directly, UPI to UPI. Separate '
    'from refund_required (032), which means a GATEWAY payment has to be '
    'reversed and feeds /admin/orders/refund-due. CareVo was never in the path '
    'of a direct-UPI payment and cannot refund it, so these must never appear '
    'in that queue.';

COMMENT ON COLUMN customers.false_claim_count IS
    'Times a restaurant reported the money never arrived after this customer '
    'claimed it had. At 2 the resolver stops offering direct UPI to them; '
    'prepaid and pay-at-pickup are unaffected. Distinct from no_show_count '
    '(034) — wasting food and asserting a payment that did not exist are '
    'different things. Cleared only by an explicit admin act.';
