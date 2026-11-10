-- 040_outlet_gateway_credentials.sql
--
-- Per-outlet, per-provider webhook secret storage for the vendor-direct
-- gateway route (Task 5). ADDITIVE ONLY. The route that reads this table is
-- gated by VENDOR_GATEWAY_ENABLED (default false) and this migration alone
-- changes no runtime behaviour.
--
-- ============================================================================
-- WHAT THIS DOES
-- ============================================================================
-- CREATE TABLE IF NOT EXISTS outlet_gateway_credentials. One row per
-- (outlet_id, provider): rotating a secret is an UPDATE of the SAME row
-- (new ciphertext, new key_id, rotated_at stamped), not an INSERT of a
-- second row -- the old plaintext secret is gone from the database the
-- moment the UPDATE commits, which is what "a rotated secret invalidates
-- the old one" means here: there is nothing left to verify an old signature
-- against.
--
-- webhook_secret_ciphertext is the OUTPUT of app.core.secrets_box (AES-256-
-- GCM; see migration-free Task 2) -- base64 text, never plaintext. key_id
-- duplicates the key id already embedded in that ciphertext, kept in its
-- own column so an operator can see which encryption key protects a row
-- without decrypting anything.
--
-- NEVER SELECTABLE BY ANY READ ENDPOINT. No route in this codebase returns
-- a row from this table; app.modules.carevo_payments.vendor_credentials is
-- the only code that SELECTs from it, and only to decrypt a secret for
-- signature verification inside the webhook route itself -- never to
-- return it to any caller.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- See docs/ops/040_outlet_gateway_credentials_rollback.sql.

CREATE TABLE IF NOT EXISTS outlet_gateway_credentials (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id                 uuid        NOT NULL REFERENCES outlets(id),
    provider                  varchar(30) NOT NULL,
    webhook_secret_ciphertext text        NOT NULL,
    key_id                    varchar(100) NOT NULL,
    created_at                timestamptz NOT NULL DEFAULT now(),
    rotated_at                timestamptz NULL,
    active                    boolean     NOT NULL DEFAULT true,

    CONSTRAINT uq_outlet_gateway_credentials_outlet_provider
        UNIQUE (outlet_id, provider)
);

COMMENT ON TABLE outlet_gateway_credentials IS
    'Per-outlet, per-provider webhook secret, encrypted at rest via '
    'app.core.secrets_box. Write-only from any API surface -- no route '
    'selects a row from this table. Rotation overwrites the ciphertext in '
    'place; the prior plaintext is unrecoverable once overwritten.';
