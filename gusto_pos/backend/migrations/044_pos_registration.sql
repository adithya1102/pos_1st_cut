-- Migration 044: POS registration codes (Gusto Skip <-> Native Gusto POS link)
--
-- Replaces open sign-up on the POS with a one-time Registration ID issued
-- from the Gusto Skip owner_app. Flow:
--   1. POST /api/v1/owner/pos-registration-code (owner auth) mints a code,
--      revoking any earlier unused code for that outlet.
--   2. POST /api/v1/pos-link/verify (public) resolves a code to outlet+owner
--      details without consuming it.
--   3. POST /api/v1/pos-link/consume (public, idempotent per pos_install_id)
--      marks the code used and stamps outlets.pos_registered_at.
--
-- NO shared-secret / HMAC server-to-server auth: /pos-link/verify and
-- /pos-link/consume are public endpoints. A secret baked into a desktop
-- installer is not a secret, so the only protections are code entropy
-- (CSPRNG, 8 chars from a 32-symbol alphabet), a 15-minute TTL, single use,
-- and rate limiting (per-IP in-memory + a DB-backed global backstop below).
--
-- Additive and idempotent, per AGENT_GUARDRAILS.md. Raw SQL, no Alembic
-- (CLAUDE.md's alembic commands are stale for this repo).

CREATE TABLE IF NOT EXISTS pos_registration_codes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id       uuid NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    -- SHA-256(code + SECRET_KEY pepper), hex. Never the plain code -- same
    -- reasoning as auth_tokens.token_hash (migration 015).
    code_hash       varchar(64) NOT NULL,
    -- 'random' (default: CSPRNG 8-char code, 15 min TTL, single use) |
    -- 'fixed-test' (code is always "1234", reusable, TTL ignored; refused
    -- outside NON_PRODUCTION_ENVS at startup -- see
    -- validate_pos_link_startup_posture in app/core/config.py).
    mode            varchar(16) NOT NULL DEFAULT 'random',
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    consumed_at     timestamptz,
    revoked_at      timestamptz,
    -- Opaque high-entropy reference handed out by /pos-link/verify and
    -- required by /pos-link/consume, hashed for the same reason code_hash
    -- is: a leaked DB dump must not hand out a live consume credential.
    registration_ref_hash varchar(64),
    pos_install_id  varchar(128),
    failed_attempts integer NOT NULL DEFAULT 0,
    CONSTRAINT ck_pos_registration_codes_mode
        CHECK (mode IN ('random', 'fixed-test'))
);

CREATE INDEX IF NOT EXISTS idx_pos_registration_codes_code_hash
    ON pos_registration_codes (code_hash);

-- "revoke any earlier unused code for that outlet" -- the lookup mint_code
-- needs before inserting the new row.
CREATE INDEX IF NOT EXISTS idx_pos_registration_codes_outlet_live
    ON pos_registration_codes (outlet_id)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_pos_registration_codes_ref_hash
    ON pos_registration_codes (registration_ref_hash)
    WHERE registration_ref_hash IS NOT NULL;

-- Idempotent consume: lets the service look up "did THIS install already
-- consume THIS row" without a table scan.
CREATE INDEX IF NOT EXISTS idx_pos_registration_codes_pos_install
    ON pos_registration_codes (pos_install_id)
    WHERE pos_install_id IS NOT NULL;

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS pos_registered_at timestamptz;

-- DB-backed GLOBAL failure counter for /pos-link/verify and /pos-link/consume.
-- Single row (id fixed at 1). Backs up the in-memory per-IP limiter, which
-- forgets everything on a restart/redeploy -- there is no Redis (confirmed:
-- AGENT_GUARDRAILS.md, and check_register_rate_limit's own docstring).
-- 50 failures/hour -> 10-minute global cooldown (app/core/config.py
-- POS_LINK_GLOBAL_FAILURE_LIMIT / _WINDOW_SECONDS / _COOLDOWN_SECONDS).
CREATE TABLE IF NOT EXISTS pos_link_rate_limit_state (
    id                 smallint PRIMARY KEY DEFAULT 1,
    window_started_at  timestamptz NOT NULL DEFAULT now(),
    failure_count      integer NOT NULL DEFAULT 0,
    cooldown_until      timestamptz,
    CONSTRAINT ck_pos_link_rate_limit_state_singleton CHECK (id = 1)
);

INSERT INTO pos_link_rate_limit_state (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

-- Rollback (manual, not run automatically):
--   DROP TABLE IF EXISTS pos_link_rate_limit_state;
--   DROP TABLE IF EXISTS pos_registration_codes;
--   ALTER TABLE outlets DROP COLUMN IF EXISTS pos_registered_at;
