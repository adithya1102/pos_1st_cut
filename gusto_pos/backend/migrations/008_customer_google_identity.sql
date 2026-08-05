-- ============================================================================
-- Customer Google identity — Migration 008
-- Branch: 21_7 | Target: existing GustoPOS Neon DB (prod neondb)
--
-- ⚠️  NOT PURELY ADDITIVE. Unlike 004/005/007 this migration relaxes ONE
--     existing constraint: customers.phone_number loses its NOT NULL. Read the
--     safety notes before running it.
--
-- WHY: Google Sign-In is a STANDALONE identity. A customer who signs in with
--      Google has no verified phone number, and we deliberately do not ask for
--      one at sign-in — the app shows "—" until they verify a phone separately.
--      phone_number therefore has to be nullable.
--
-- SAFETY CONTRACT:
--   * Two new nullable columns (email, google_uid) — additive, no default, so
--     no table rewrite.
--   * DROP NOT NULL is a catalog-only change in Postgres: instant, no rewrite,
--     brief ACCESS EXCLUSIVE lock. It does NOT touch existing rows, all of
--     which keep their phone number.
--   * The existing UNIQUE on phone_number is UNTOUCHED and still does its job:
--     Postgres UNIQUE permits many NULLs, so Google-only rows never collide.
--   * Idempotent: IF NOT EXISTS everywhere + a guarded DO block for the CHECK.
--   * No data is written, moved, or deleted.
--
-- REVERSIBILITY: re-adding NOT NULL is only possible while no NULL-phone row
--   exists. Once the first Google-only customer signs up, the rollback is
--   "delete/backfill those rows first" — not a plain ALTER. Roll back before
--   the app ships, not after.
--
-- ORDERING: apply this BEFORE deploying the backend that serves
--   POST /api/v1/customer/auth/google. The endpoint inserts NULL phone_number
--   and will 500 against the pre-migration schema.
-- ============================================================================

-- 1. Standalone Google identity columns.
ALTER TABLE customers ADD COLUMN IF NOT EXISTS email      VARCHAR(255);
ALTER TABLE customers ADD COLUMN IF NOT EXISTS google_uid VARCHAR(128);

-- 2. Phone becomes optional — a Google customer has none until they verify one.
ALTER TABLE customers ALTER COLUMN phone_number DROP NOT NULL;

-- 3. One account per Google identity. Unique INDEXes (not constraints) so the
--    IF NOT EXISTS form is available; NULLs are exempt, so the millions of
--    phone-only rows are unaffected and never collide with each other.
CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_google_uid
    ON customers (google_uid) WHERE google_uid IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_email
    ON customers (LOWER(email)) WHERE email IS NOT NULL;

-- 4. Safety net: a customer row must carry at least one usable identity, so
--    dropping NOT NULL above can never yield an unreachable account. Every
--    existing row satisfies this (they all have a phone), so validation is
--    a cheap scan on a small table.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'customers_identity_present'
    ) THEN
        ALTER TABLE customers ADD CONSTRAINT customers_identity_present
            CHECK (phone_number IS NOT NULL OR google_uid IS NOT NULL);
    END IF;
END $$;
