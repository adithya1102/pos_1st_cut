-- Migration 020: train transport mode (Timing Engine addendum, Item 1)
--
-- SMALLER THAN THE SPEC ANTICIPATED. The spec allowed for three schema
-- changes; two turned out to be unnecessary once checked against
-- information_schema rather than model.py:
--
--  1. transport_mode accepting 'train' -> NO DDL NEEDED.
--     customer_orders.transport_mode is `text`, nullable, and
--     customer_orders has NO check constraints at all (verified via
--     pg_constraint WHERE contype='c' -> zero rows). Values in use today are
--     bike/walk/car and NULL. 'train' is already a legal value; the enum
--     lives only in the app layer.
--
--  2. Per-outlet last-mile constant -> NO NEW COLUMN NEEDED.
--     outlet_config already exists as a per-outlet key/value table
--     (outlet_id, config_key, config_value). The constant is stored there
--     under config_key = 'train_last_mile_seconds'. The table is currently
--     empty, so this introduces the first key rather than following an
--     existing convention — the reader in code therefore treats a missing
--     row as "use the documented default", never as an error.
--
-- So this migration adds exactly one column.

-- 0. SCHEMA DRIFT, codified. -------------------------------------------------
-- outlet_config exists in prod and is read AND written by live code
-- (app/modules/config/controller.py, raw SQL), but is created by no ORM model
-- and no migration — it was made by hand. Same class of gap as
-- menu_items.tags (migration 019); found the same way, by a fresh database
-- failing where prod does not.
--
-- It matters here because §1 of this spec resolves the per-outlet last-mile
-- constant onto this table instead of a new column. That answer is only
-- correct if the table is actually part of the repo.
--
-- NO-OP ON PROD: IF NOT EXISTS, and the shape below was read back from the
-- live schema rather than invented.
-- Every column below was read back COLUMN-BY-COLUMN from
-- information_schema.columns and pg_constraint on the live database. A first
-- draft of this block was written from notes and got three things wrong
-- (config_key varchar(64) not 100, config_value nullable not NOT NULL,
-- updated_at missing its default) plus declared the uniqueness as a
-- separately-named index. None of that would ever show on prod, because
-- IF NOT EXISTS makes this a no-op there — it would only ever have bitten a
-- fresh database, which is precisely where this table is missing today.
--
-- The UNIQUE is written as a table constraint, not CREATE UNIQUE INDEX, so a
-- fresh database reproduces prod's constraint name
-- (outlet_config_outlet_id_config_key_key) rather than a parallel one.
CREATE TABLE IF NOT EXISTS outlet_config (
    id           uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    outlet_id    uuid NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    config_key   varchar(100) NOT NULL,
    config_value text NOT NULL,
    updated_at   timestamp DEFAULT now(),
    created_at   timestamp DEFAULT now(),
    -- One value per key per outlet. The upsert in config/controller.py already
    -- assumes this; without it a repeated write silently accumulates duplicate
    -- rows and the reader picks one arbitrarily.
    UNIQUE (outlet_id, config_key)
);

-- 1. The customer's own stated arrival time. Only meaningful when
-- transport_mode = 'train'; NULL for every other mode and for every order
-- that predates this migration.
--
-- Deliberately NOT constrained to train-only at the DB level. A CHECK tying
-- it to transport_mode would be a new restriction on a live table whose
-- existing rows were never validated, and the column is inert for other
-- modes anyway — predict_travel only reads it inside the train branch.
--
-- timestamptz, matching every other instant in this schema. It is an
-- absolute arrival moment, not a duration, because a duration would silently
-- rot between the customer entering it and the kitchen acting on it.
ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS declared_arrival_at timestamptz;

-- Supports the check-on-read sweep in §3, which asks "any train order due
-- for kitchen notification?" on every GET /pos/orders. Partial, because only
-- train orders ever populate this column — the index stays tiny regardless of
-- how large customer_orders grows.
CREATE INDEX IF NOT EXISTS idx_customer_orders_declared_arrival
    ON customer_orders (declared_arrival_at)
    WHERE declared_arrival_at IS NOT NULL;

-- The new push kind. Caught before shipping this time: push_notifications.kind
-- carries an enumerated CHECK, and migration 018 exists precisely because 017
-- added a kind without widening it — the log INSERT is best-effort
-- (try/except), so the rejection was SILENT and only surfaced as duplicate
-- pushes when the idempotency guard found no rows.
--
-- order_events.event_type needs no equivalent change: it has no CHECK
-- (verified via pg_constraint), so KITCHEN_START_NOTIFIED just works.
ALTER TABLE push_notifications
    DROP CONSTRAINT IF EXISTS push_kind_valid;

ALTER TABLE push_notifications
    ADD CONSTRAINT push_kind_valid CHECK (kind IN (
        'ORDER_STATUS',
        'REENGAGEMENT',
        'DISH_SUGGESTION',
        'STAFF_NEW_ORDER',
        'ITEM_UNAVAILABLE',
        -- addendum Item 1: "start this order now", train orders only
        'TRAIN_START_DUE'
    ));
