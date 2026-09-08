-- Migration 021: outlet relocation request (SCHEMA ONLY — no workflow yet)
--
-- Companion to migration 012, which added `outlets.locality`. 012 made an
-- outlet's area recordable; this makes a *change* to that area recordable
-- without overwriting the live value.
--
-- WHY A PENDING SHADOW COPY RATHER THAN AN EDIT IN PLACE: locality is not
-- cosmetic once §4 lands. It is half of the (city, location_name, locality)
-- uniqueness rule that admin approval enforces, and it is what the customer
-- sees under the restaurant name. Letting an owner rewrite it directly would
-- let them walk around that rule after approval, and would silently move the
-- restaurant on every customer's screen with no admin ever seeing it.
--
-- MODELLED ON verification_status: a proposed value sits beside the live one
-- and an admin promotes or discards it. Nothing here changes what any existing
-- read does — every query in the app today reads `locality`, not
-- `pending_locality`, so these columns are inert until a later session builds
-- the workflow.
--
-- SCOPE: schema only, deliberately. No endpoint, no admin queue, no UI. The
-- columns exist now so the locality work lands once instead of needing a second
-- migration against a table that will by then have live locality data.

-- The proposed new area, and the coordinates that go with it. Nullable with no
-- default: NULL means "no relocation proposed", which is every existing row and
-- every outlet that never moves.
--
-- varchar(80) and numeric mirror `locality`, `latitude` and `longitude` exactly
-- rather than picking fresh types — a pending value must be able to hold
-- anything the live column can hold, or promotion could fail on a value the
-- owner was allowed to submit.
ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS pending_locality varchar(80);

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS pending_latitude numeric;

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS pending_longitude numeric;

-- The gate flag the future admin queue filters on.
--
-- NOT NULL DEFAULT false rather than nullable, which is the one place this
-- deviates from "nullable columns" as specified. A nullable boolean would carry
-- three states (true / false / NULL) for a question that has two, and every
-- reader would then have to spell `IS NOT TRUE` to avoid NULL propagation.
-- Postgres applies the default without rewriting the table, so this stays a
-- fast, additive change on a live table.
--
-- Kept SEPARATE from pending_locality rather than inferring "pending" from
-- "pending_locality IS NOT NULL": an owner may propose only new coordinates
-- (same area name, corrected pin), which would otherwise be invisible to the
-- queue.
ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS relocation_is_pending boolean NOT NULL DEFAULT false;

-- The admin queue's "outlets awaiting a relocation decision" read. Partial, so
-- it stays the size of the queue rather than the size of `outlets` — the flag
-- is false for essentially every row at any given moment.
CREATE INDEX IF NOT EXISTS idx_outlets_relocation_pending
    ON outlets (relocation_is_pending)
    WHERE relocation_is_pending = true;
