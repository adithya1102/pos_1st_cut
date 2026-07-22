-- ============================================================================
-- CareVo Admin Dashboard — Additive migration 003
-- Branch: 21_7 | Target: existing GustoPOS Neon DB
--
-- *** CHECKPOINT A — NOT APPLIED. Requires explicit "approved" before running.
--
-- SAFETY CONTRACT:
--   * ADDITIVE ONLY. No DROP, no ALTER of an existing column's type, no
--     rewriting of existing row data beyond the column default backfill that
--     ADD COLUMN ... DEFAULT performs (every existing outlet becomes 'active',
--     i.e. exactly its pre-migration behaviour).
--   * Touches exactly ONE existing table (outlets) — one new column with a
--     safe default. Plus one INSERT of a single new roles row.
--   * Everything else is CREATE TABLE / CREATE INDEX IF NOT EXISTS.
--   * Does NOT touch: customers, menu_items, customer_orders,
--     customer_order_items, payment_transactions, orders, order_items,
--     payments, users, user_roles, or any waiter/KDS/billing table or flow.
--   * Idempotent: safe to run more than once.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1) outlets.verification_status  (the only change to a live table)
--
--    Lifecycle: pending_verification -> active | rejected
--    DEFAULT 'active' so every outlet that already exists (seeded demo data,
--    live pilot outlets) keeps working untouched. Only outlets created AFTER
--    this migration, by a flow that explicitly sets 'pending_verification',
--    ever land in the admin approval queue.
--
--    NOTE: outlets.is_visible (migration 002) is a SEPARATE, orthogonal flag —
--    it stays the owner's discovery toggle. verification_status is the
--    platform's gate. Nothing here reads or writes is_visible.
-- ----------------------------------------------------------------------------
ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS verification_status varchar(24) NOT NULL DEFAULT 'active';

-- Value guard, added separately so re-runs do not error on an existing constraint.
-- NOT VALID would skip checking existing rows; we do NOT use it — every existing
-- row is 'active' by the default above and therefore already passes.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_outlets_verification_status'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT ck_outlets_verification_status
            CHECK (verification_status IN ('pending_verification', 'active', 'rejected'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_outlets_verification_status
    ON outlets (verification_status);

-- ----------------------------------------------------------------------------
-- 2) SUPER_ADMIN role  (data insert, no DDL)
--
--    Reuses the EXISTING roles table + users<->user_roles many-to-many. No new
--    auth system, no new column on users. A staff account becomes a super admin
--    purely by gaining this role row — see step 4 below (NOT run here).
--
--    roles.id is SERIAL; roles.name is UNIQUE, so ON CONFLICT is a no-op re-run.
--
--    created_at is supplied explicitly: roles.created_at is NOT NULL but has NO
--    database-side default (the ORM Base fills it in Python), so an INSERT that
--    omits it fails with a not-null violation.
-- ----------------------------------------------------------------------------
INSERT INTO roles (name, permissions, created_at)
VALUES (
    'SUPER_ADMIN',
    '{"admin_dashboard": true, "outlet_verification": true, "order_unlock": true}'::jsonb,
    now()
)
ON CONFLICT (name) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 3) admin_audit_logs  (new isolated table)
--
--    Deliberately SEPARATE from the existing audit_logs table: audit_logs is
--    generic (user_id / action / table_name / ref_id) and is written by other
--    parts of the system. Platform-admin actions get their own append-only
--    table so the admin trail can never be diluted or truncated by unrelated
--    writers, and so actor_username survives even if the user row is removed.
--
--    Append-only by convention — nothing in the admin module UPDATEs or DELETEs
--    from this table.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    actor_user_id   uuid REFERENCES users(id),   -- nullable: survives user deletion
    actor_username  varchar(50),                 -- denormalised snapshot

    -- e.g. outlet.approve | outlet.reject | order.unlock
    action          varchar(50)  NOT NULL,
    target_type     varchar(30),                 -- 'outlet' | 'customer_order'
    target_id       uuid,

    -- free-form before/after context, e.g. {"from":"pending_verification","to":"active"}
    detail          jsonb,

    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_created_at
    ON admin_audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_target
    ON admin_audit_logs (target_type, target_id);

COMMIT;


-- ============================================================================
-- 4) GRANTING SUPER_ADMIN — NOT part of this migration. Run separately, and
--    only with explicit approval (guardrails §5: data writes to a real DB).
--
--    INSERT INTO user_roles (user_id, role_id)
--    SELECT u.id, r.id
--    FROM users u, roles r
--    WHERE u.username = '<the-super-admin-username>' AND r.name = 'SUPER_ADMIN'
--    ON CONFLICT DO NOTHING;
--
-- ROLLBACK (if ever needed — destructive, needs its own approval):
--    DROP TABLE IF EXISTS admin_audit_logs;
--    DELETE FROM user_roles WHERE role_id = (SELECT id FROM roles WHERE name='SUPER_ADMIN');
--    DELETE FROM roles WHERE name = 'SUPER_ADMIN';
--    ALTER TABLE outlets DROP CONSTRAINT IF EXISTS ck_outlets_verification_status;
--    ALTER TABLE outlets DROP COLUMN IF EXISTS verification_status;
-- ============================================================================
