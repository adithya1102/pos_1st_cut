-- Migration 015: owner recovery email + password reset tokens
--
-- Additive and idempotent.
--
-- WHY users, NOT outlets
-- The mission said "the table that holds the phone field" (outlets.phone_number,
-- migration 009), but forgot-password looks up by USERNAME, which is unique per
-- `users` row. An outlet can have several staff users, so an outlet-level email
-- would make them share one recovery address — and `carevo_admin` has no outlet
-- at all (outlet_id IS NULL), so it could never recover. Recovery identity
-- belongs to the account, not the venue.
--
-- EXISTING ROWS
-- All 7 current users have no email. The column is therefore NULLABLE with no
-- backfill: making it NOT NULL would lock every existing owner out of their own
-- account on the next deploy. "Required" is enforced at SIGNUP only (Pydantic +
-- the Flutter form), so new accounts always have one while existing accounts
-- keep working and are prompted to add one after login.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email varchar(255);

-- Verification state. NULL = never verified. Set when the emailed link is used.
-- Deliberately NOT gating login: an unverified owner can still sign in, because
-- email sending is not configured yet (see EMAIL_ENABLED) and blocking login on
-- a mail we cannot send would strand every new signup.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email_verified_at timestamptz;

-- Case-insensitive uniqueness, same reasoning as cities.name in migration 013:
-- "Owner@x.com" and "owner@x.com" are the same mailbox and must not both exist.
-- Partial, so the many NULL rows are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
    ON users (lower(email)) WHERE email IS NOT NULL;

-- Single-use, expiring tokens for both flows -----------------------------------
-- One table, two purposes, distinguished by `kind`: they share an identical
-- lifecycle (issue -> single use -> spent/expired) and differ only in effect.
CREATE TABLE IF NOT EXISTS auth_tokens (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- PASSWORD_RESET | EMAIL_VERIFY
    kind       varchar(20) NOT NULL,
    -- SHA-256 of the token, never the token itself. A leaked database dump must
    -- not hand out working reset links — same reasoning as hashed_password.
    token_hash varchar(64) NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    used_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT auth_tokens_kind_valid CHECK (kind IN ('PASSWORD_RESET', 'EMAIL_VERIFY'))
);

-- Lookup path for "does this user already have a live token of this kind?",
-- which is what rate-limits reset requests.
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_kind
    ON auth_tokens (user_id, kind, created_at DESC);
