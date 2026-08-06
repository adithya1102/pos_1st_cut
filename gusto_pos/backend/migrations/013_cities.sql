-- Migration 013: canonical city list
--
-- Additive and idempotent. Replaces free-text `outlets.city` entry at owner
-- signup with a reference list, so "Bangalore" / "Bengaluru" can never diverge
-- again (that split already happened once and needed a manual data merge).
--
-- Deliberately NOT a full geo hierarchy: no states, no districts, no
-- lat/lng, no external dataset. One flat list of city names the platform
-- actually serves, maintained by admins. Same reasoning as migration 012.
--
-- `outlets.city` is intentionally left as-is (varchar, no FK) for now: adding a
-- foreign key would be a breaking change to a live column, and the seed below
-- is what makes a future FK possible by guaranteeing every existing value has a
-- matching row. Introduce the constraint in a later migration once signup has
-- been writing canonical names for a while.

CREATE TABLE IF NOT EXISTS cities (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       varchar(80) NOT NULL,
    -- active  = selectable at signup
    -- pending = requested by an owner, awaiting admin approval
    -- rejected= declined; kept (not deleted) so the same name is not re-queued
    --           endlessly and the decision stays auditable
    status     varchar(12) NOT NULL DEFAULT 'pending',
    -- Who asked for it, for the admin queue. NULL for seeded/admin-added rows.
    requested_by_outlet_id uuid REFERENCES outlets(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    CONSTRAINT cities_status_valid CHECK (status IN ('active', 'pending', 'rejected'))
);

-- Case-insensitive uniqueness: "kochi" and "Kochi" must not both exist, which
-- is the whole point of this table. Functional unique index rather than a
-- plain UNIQUE(name) so the guarantee survives casing differences.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cities_name_lower
    ON cities (lower(name));

CREATE INDEX IF NOT EXISTS idx_cities_status ON cities (status);

-- Seed EVERY city that currently has an outlet, all active.
--
-- Kochi is included deliberately: outlet 'Kochi_test' (created 2026-08-06) is
-- live and visible with city='Kochi'. Seeding only Chennai + Bengaluru would
-- leave that outlet referencing a city absent from the canonical list, which is
-- exactly the inconsistency this table exists to prevent — and would block a
-- future FK.
--
-- ON CONFLICT DO NOTHING keeps the migration re-runnable.
INSERT INTO cities (name, status)
VALUES ('Bengaluru', 'active'),
       ('Chennai',   'active'),
       ('Kochi',     'active')
ON CONFLICT (lower(name)) DO NOTHING;
