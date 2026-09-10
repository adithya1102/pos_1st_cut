-- Migration 029: city transport profile (city_type + rail flags)
--
-- Additive and idempotent. Moves "which travel modes does this city support?"
-- out of a const map compiled into customer_app and onto a row an admin can
-- edit, which is what makes a NEW metro city light up without an app release.
--
-- ## Why this lives on `cities` and not a new table
--
-- Migration 013 already created the canonical, admin-maintained city list with
-- case-insensitive uniqueness, and the admin dashboard already has a page for
-- it. A second table keyed on the same names would give two answers to "what is
-- Chennai" — the exact split 013 exists to prevent. Two columns here instead.
--
-- ## `outlets.city` is still free text
--
-- 013 deliberately left `outlets.city` as varchar with no FK, so the join back
-- to this row is `lower(cities.name) = lower(outlets.city)` — the same
-- lower()-on-both-sides rule `list_outlets` already uses. A city with an outlet
-- but no `cities` row (possible until the FK lands) resolves to NULL, and the
-- app treats NULL as "no server answer" and falls back to its built-in map.
-- Absent still means safe, exactly as before.
--
-- ## Seeded to today's behaviour, so nothing moves on deploy
--
-- has_train is seeded from customer_app's CityTransport._hasRail EXACTLY as it
-- ships today (Chennai, Bengaluru, Kolkata, Kochi true; Madurai false). This
-- migration must not change a single customer's options at the moment it runs —
-- Metro is a new option appearing, not Train quietly disappearing somewhere.

ALTER TABLE cities
    ADD COLUMN IF NOT EXISTS city_type varchar(16) NOT NULL DEFAULT 'tier_2';

-- Rail a customer can arrive on, INDEPENDENT of city_type.
--
-- Separate from city_type on purpose: Madurai is a tier-2 city with a major
-- mainline junction and no metro, and a scheme that derived both flags from one
-- radio button could not say that. The admin sets the type; rail is its own
-- answer.
ALTER TABLE cities
    ADD COLUMN IF NOT EXISTS has_train boolean NOT NULL DEFAULT false;

ALTER TABLE cities
    ADD COLUMN IF NOT EXISTS transport_updated_at timestamptz;

-- metro   = has an urban metro/rapid-transit system (Chennai, Namma, Kolkata, Kochi)
-- tier_1  = large city, no metro
-- tier_2  = default for everything else; the safe landing spot for a new signup
-- tier_3  = small town
--
-- NOT VALID is deliberate: it enforces the rule for every future write without
-- re-scanning a live table behind an ACCESS EXCLUSIVE lock. The DEFAULT above
-- means no existing row can violate it anyway.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'cities_city_type_valid'
    ) THEN
        ALTER TABLE cities
            ADD CONSTRAINT cities_city_type_valid
            CHECK (city_type IN ('metro', 'tier_1', 'tier_2', 'tier_3')) NOT VALID;
    END IF;
END $$;

-- --------------------------------------------------------------------------
-- Seed: the four cities customer_app already treats as rail cities.
--
-- All four also run metros, which is why city_type and has_train agree for
-- every row today. They will not stay in lockstep — that is the point of them
-- being two columns.
-- --------------------------------------------------------------------------
UPDATE cities
   SET city_type = 'metro',
       has_train = true,
       transport_updated_at = now()
 WHERE lower(name) IN ('chennai', 'bengaluru', 'kolkata', 'kochi')
   AND city_type = 'tier_2';   -- only rows still on the default; never clobber
                               -- a value an admin has already chosen

-- Madurai and anything else stay tier_2 / has_train=false, which is exactly
-- what CityTransport returns for them today (absent from _hasRail => false).

CREATE INDEX IF NOT EXISTS idx_cities_city_type ON cities (city_type);
