-- Migration 012: outlet locality (PROPOSED — NOT APPLIED)
--
-- Smallest addition that would let the location picker offer sub-city areas
-- ("Koramangala", "Indiranagar") instead of only cities.
--
-- WHY THIS IS THE MINIMUM: `outlets` already has `city varchar(50)`. It has no
-- locality/area/neighbourhood column of any kind, so today the picker can only
-- go to city granularity. One nullable column closes that gap. Deliberately NOT
-- a state -> city -> locality reference hierarchy with its own tables: that is
-- a generic India-wide geo dataset, which is out of scope and would need
-- sourcing, seeding and maintenance far beyond what a picker needs.
--
-- Nullable with no backfill: existing outlets have no locality on record, and
-- the picker treats NULL as "city-level only" rather than inventing a value.
-- GET /customer/areas keeps working unchanged until localities are populated.
--
-- varchar(80) not (50): locality names run longer than city names
-- ("Electronic City Phase 1", "HSR Layout Sector 2").

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS locality varchar(80);

-- Supports the picker's GROUP BY on (city, locality) for visible outlets.
CREATE INDEX IF NOT EXISTS idx_outlets_city_locality
    ON outlets (city, locality)
    WHERE is_visible = true AND deactivated_at IS NULL;
