-- Migration 030: normalized per-city transport modes
--
-- Replaces migration 029's column-per-mode shape with two tables. 029 stored
-- "does this city have rail?" as `has_train boolean` plus a metro flag DERIVED
-- from `city_type = 'metro'`. That shape cannot grow: every new mode is a new
-- column, a new migration, a new backend field, a new app field. Adding Tram
-- under 029 would have meant `has_tram boolean` and the whole chain again.
--
-- Here, adding a ninth mode is ONE INSERT into `transport_modes` and nothing
-- else. No DDL, no deploy, no app release for it to appear in the admin UI.
--
-- ## Two tables, not one
--
--   transport_modes       the CATALOG: which modes exist at all, and how each
--                         one behaves. Rows here are the platform's vocabulary.
--   city_transport_modes  the per-city ON/OFF grid. One row per (city, mode).
--
-- The catalog is what makes the admin UI generic: it renders however many rows
-- this table has, so a mode added next year needs no frontend change either.
--
-- ## `city_type` is KEPT, and DECOUPLED
--
-- 029 conflated two questions into one column: "what size/kind of city is
-- this?" and "does it offer Metro?". Metro-ness now lives in the grid below,
-- where it belongs. `city_type` survives as what its name always claimed —
-- a standalone classification.
--
-- It is deliberately NOT dropped. Nothing outside the transport feature reads
-- it today (verified by sweep), so dropping it would be safe in the narrow
-- sense — but it is populated real data that was explicitly asked for as a
-- city tiering field, and an unused column costs nothing while an irreversible
-- DROP of populated data costs everything if the judgement was wrong. After
-- this migration it drives NO behaviour: `has_metro` comes from the grid.

-- --------------------------------------------------------------------------
-- 1. The catalog
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transport_modes (
    -- Matches the `transport_mode` string already stored on customer_orders
    -- and the `wire` value in customer_app's enum. One vocabulary, three
    -- places, no translation layer.
    code                  varchar(24) PRIMARY KEY,
    label                 varchar(48) NOT NULL,

    -- TRUE  -> the customer states an arrival TIME (train, metro, tram):
    --          no GPS origin, no speed, and the kitchen is timed backwards
    --          from the stated moment.
    -- FALSE -> ordinary speed-based travel from a GPS origin.
    --
    -- Lives here rather than in app code so a new declared-arrival mode
    -- behaves correctly in an app build that has never heard of it.
    uses_declared_arrival boolean NOT NULL DEFAULT false,

    -- What a city gets when nobody has decided yet. Walking and road transport
    -- exist everywhere, so they default ON; anything rail-shaped defaults OFF
    -- because offering it where it does not exist collects a declared arrival
    -- for a journey that cannot happen.
    default_enabled       boolean NOT NULL DEFAULT false,

    -- Display order in both the admin grid and the customer chip row, so the
    -- two cannot drift into different orders.
    sort_order            integer NOT NULL DEFAULT 100,

    -- Retire a mode without deleting it and cascading away every city's row
    -- (and the audit trail of who turned it on).
    is_active             boolean NOT NULL DEFAULT true,

    created_at            timestamptz NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------
-- 2. The per-city grid
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS city_transport_modes (
    city_id    uuid        NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
    mode_code  varchar(24) NOT NULL REFERENCES transport_modes(code) ON DELETE CASCADE,
    enabled    boolean     NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (city_id, mode_code)
);

CREATE INDEX IF NOT EXISTS idx_city_transport_modes_city
    ON city_transport_modes (city_id);

-- --------------------------------------------------------------------------
-- 3. Seed the catalog
--
-- ON CONFLICT DO NOTHING, not DO UPDATE: re-running this must not reset a
-- label or a default someone deliberately changed later.
-- --------------------------------------------------------------------------
INSERT INTO transport_modes
    (code, label, uses_declared_arrival, default_enabled, sort_order)
VALUES
    ('walk',  'Walk',  false, true,  10),
    ('bike',  'Bike',  false, true,  20),
    ('car',   'Car',   false, true,  30),
    ('auto',  'Auto',  false, true,  40),
    ('bus',   'Bus',   false, true,  50),
    -- Declared-arrival modes. All three are scheduled services the customer
    -- reads a time off, so a GPS origin would be collected and then ignored.
    ('train', 'Train', true,  false, 60),
    ('metro', 'Metro', true,  false, 70),
    -- New in this migration. Starts OFF everywhere: no city has been checked
    -- for a tram network, and the safe default is silence.
    ('tram',  'Tram',  true,  false, 80)
ON CONFLICT (code) DO NOTHING;

-- --------------------------------------------------------------------------
-- 4. Carry 029's data across
--
-- The CASE is the whole migration. Everything not named explicitly takes the
-- catalog default, which is what makes this correct for a ninth mode added
-- later as well as for the five road modes today.
--
--   train -> cities.has_train verbatim
--   metro -> the derived rule 029 used: city_type = 'metro'
--   tram  -> false everywhere, per the catalog default
--   rest  -> default_enabled (true for walk/bike/car/auto/bus)
--
-- ON CONFLICT DO NOTHING so a re-run cannot overwrite an admin's later choice
-- with the frozen 029 snapshot.
-- --------------------------------------------------------------------------
INSERT INTO city_transport_modes (city_id, mode_code, enabled)
SELECT c.id,
       m.code,
       CASE m.code
           WHEN 'train' THEN COALESCE(c.has_train, false)
           WHEN 'metro' THEN (c.city_type = 'metro')
           ELSE m.default_enabled
       END
FROM cities c
CROSS JOIN transport_modes m
ON CONFLICT (city_id, mode_code) DO NOTHING;

-- --------------------------------------------------------------------------
-- 5. A city with no row for a mode reads as the catalog default
--
-- There is deliberately NO trigger backfilling new cities. The read path
-- LEFT JOINs the catalog and COALESCEs to `default_enabled`, so a city created
-- by any code path — signup, admin, a hand-written INSERT — behaves correctly
-- from the moment it exists, with no row required. Writes UPSERT.
--
-- A trigger would be a second mechanism that has to agree with the read path
-- forever; this way there is only one rule: absent means default.
-- --------------------------------------------------------------------------

-- 029's columns are intentionally left in place. `has_train` is now a
-- historical record of what 029 knew, not a live input: nothing reads it after
-- this migration. It is kept for one release so a rollback has something to
-- roll back TO, and so the carry-across above stays re-runnable.
