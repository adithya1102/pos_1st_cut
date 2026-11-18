-- 043_meal_slots.sql
--
-- Meal-time slots: the owner groups dishes into up to four named slots
-- (morning / afternoon / evening / night) and switches the whole menu to one
-- of them in a single tap.
--
-- WHAT PROBLEM THIS SOLVES
-- ============================================================================
-- Today the only way to change what is orderable is one dish at a time:
-- PATCH /pos/menu-items/{id}/availability, one HTTP call per dish, and there
-- is no bulk route (there never has been). A restaurant with a breakfast menu
-- and a dinner menu does that arithmetic by hand twice a day, on a phone,
-- and the failure mode is not an error message — it is a dosa that is still
-- orderable at 9pm because the owner got to row 14 and was interrupted.
--
-- A slot stores the owner's INTENT ("these are the breakfast dishes") so the
-- switch becomes one action whose correctness does not depend on how many
-- dishes the restaurant has.
--
-- ============================================================================
-- TWO NEW TABLES. NO EXISTING TABLE IS ALTERED.
-- ============================================================================
-- Nothing is added to `menu_items` and nothing is added to `outlets`. That is
-- the whole reason this is two tables rather than a column: a dish belongs to
-- MANY slots (a lassi is on breakfast and dinner), which a column on
-- menu_items cannot express without an array or a comma string. The existing
-- availability column `menu_items.is_available` remains the ONE customer-
-- facing gate and keeps its exact present meaning — applying a slot WRITES
-- that column and introduces no second notion of availability. There is
-- deliberately no "active slot" column anywhere: what is currently on is
-- derivable from is_available, and storing it too would create two sources of
-- truth that drift the first time somebody toggles one dish by hand.
--
--   outlet_meal_slots — one row per (outlet, slot_key). At most four per
--     outlet, enforced by the CHECK on slot_key plus UNIQUE(outlet_id,
--     slot_key); there is no fifth legal key, so "up to four" is a schema
--     fact rather than an application convention.
--
--     start_time / end_time are `time` and NULLABLE, and they are DISPLAY
--     ONLY. Nothing in this migration or in the application reads them to
--     decide anything: they are the label on the chip ("7:00 - 11:00"), so an
--     owner can tell the four slots apart. They are NOT a schedule and
--     NOTHING auto-applies a slot when the clock reaches start_time. The
--     operating-hours columns from migration 024 (opens_at / closes_at,
--     evaluated by CarevoService.outlet_availability) are the only times this
--     system acts on, and they gate ORDERING, not dish availability. `time`
--     rather than text so a malformed value is refused by the database, and
--     nullable because a slot is useful with a dish set and no times at all.
--
--   meal_slot_items — the membership set. PRIMARY KEY (slot_id,
--     menu_item_id) IS the de-duplication: adding the same dish twice is a
--     no-op by construction rather than something the API has to filter. No
--     surrogate id, because the pair is the identity and nothing ever needs
--     to reference one membership row.
--
-- CASCADE ON BOTH FOREIGN KEYS, each for its own reason:
--   slot_id -> outlet_meal_slots  : deleting a slot deletes its membership.
--   menu_item_id -> menu_items    : a dish removed from the menu leaves every
--     slot it was in. Without this, DELETE /pos/menu-items/{id} would start
--     failing with a foreign-key violation the moment a dish was in a slot —
--     i.e. this feature would silently break an existing endpoint. Note the
--     existing delete is a SOFT delete (service.py sets is_active = false),
--     so this path is for a real row removal; it is correct either way.
--   outlet_id -> outlets          : CASCADE, matching how outlet-owned
--     configuration already behaves.
--
-- ============================================================================
-- INERT ON DEPLOY
-- ============================================================================
-- Both tables are created EMPTY. No row anywhere is read or written by this
-- migration, no column is altered, no default changes. Every existing query
-- returns exactly what it returned before, because no existing query names
-- these tables. An outlet with no slot rows is indistinguishable from today:
-- GET /pos/meal-slots synthesises the four keys with empty item lists, and a
-- slot with no items refuses to apply (422 SLOT_EMPTY) rather than turning
-- the entire menu off — which is the one destructive reading of "apply the
-- empty set" and is why it is refused rather than allowed.
--
-- Fully idempotent: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
-- throughout, so re-running changes nothing.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   DROP TABLE IF EXISTS meal_slot_items;
--   DROP TABLE IF EXISTS outlet_meal_slots;
--
-- Clean at any time and in that order (the child first, or use CASCADE).
-- Dropping these loses the owner's saved groupings and nothing else: whatever
-- `menu_items.is_available` happened to be at that moment is left exactly as
-- it stands, because a slot only ever wrote that column and never owned it.
-- No payment, order, or customer row is touched by this migration or by any
-- code that reads these tables.

CREATE TABLE IF NOT EXISTS outlet_meal_slots (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id   uuid NOT NULL REFERENCES outlets (id) ON DELETE CASCADE,
    slot_key    varchar(16) NOT NULL,
    start_time  time NULL,
    end_time    time NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_outlet_meal_slots_slot_key
        CHECK (slot_key IN ('morning', 'afternoon', 'evening', 'night')),
    CONSTRAINT ux_outlet_meal_slots_outlet_slot
        UNIQUE (outlet_id, slot_key)
);

CREATE TABLE IF NOT EXISTS meal_slot_items (
    slot_id      uuid NOT NULL
                 REFERENCES outlet_meal_slots (id) ON DELETE CASCADE,
    menu_item_id uuid NOT NULL
                 REFERENCES menu_items (id) ON DELETE CASCADE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (slot_id, menu_item_id)
);

-- The PRIMARY KEY already indexes (slot_id, menu_item_id), which serves every
-- "what is in this slot" read. This index is for the OTHER direction — "which
-- slots is this dish in" — which is what the menu-item delete cascade walks,
-- and a cascade without it degrades to a sequential scan of the whole
-- membership table per deleted dish.
CREATE INDEX IF NOT EXISTS ix_meal_slot_items_menu_item
    ON meal_slot_items (menu_item_id);

COMMENT ON TABLE outlet_meal_slots IS
    'Owner-defined meal-time slots, at most four per outlet (morning, '
    'afternoon, evening, night). start_time/end_time are DISPLAY ONLY -- '
    'nothing auto-applies a slot when the clock reaches them; see migration '
    '024 opens_at/closes_at for the times that actually gate ordering.';
COMMENT ON COLUMN outlet_meal_slots.start_time IS
    'Display-only label for the slot chip. Not a schedule. Nullable.';
COMMENT ON COLUMN outlet_meal_slots.end_time IS
    'Display-only label for the slot chip. Not a schedule. Nullable.';
COMMENT ON TABLE meal_slot_items IS
    'Which dishes belong to a slot. A dish may be in several slots. Applying '
    'a slot sets menu_items.is_available = true for these and false for every '
    'other dish of the outlet; is_available remains the single customer-'
    'facing availability gate.';
