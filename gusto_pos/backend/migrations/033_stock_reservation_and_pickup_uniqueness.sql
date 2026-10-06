-- 033_stock_reservation_and_pickup_uniqueness.sql
--
-- Two independent problems that both come down to "two requests raced and the
-- database did not stop them".
--
--   (a) OVERSELLING. There is no stock concept on the customer path at all
--       today — the only gate is menu_items.is_available, a boolean with no
--       count behind it. Two customers ordering the last unit both succeed,
--       because nothing is ever decremented. Verified: carevo_customer/
--       service.py resolves items with a plain SELECT and checks
--       `is_available AND is_active`; there is no SELECT ... FOR UPDATE and no
--       with_for_update() anywhere in the file.
--
--       (`inventory.current_stock` and `products.stock_qty` DO exist, but they
--       belong to legacy staff-gated POS modules, hold 0 rows, are created by
--       ORM metadata rather than any migration, and no customer-path code
--       references them. They are not the mechanism.)
--
--   (b) PICKUP-CODE COLLISIONS. _generate_pickup_code loops up to 30 times
--       SELECTing to see whether a candidate is already live at that outlet,
--       then returns it. The check and the INSERT are not atomic and take no
--       lock, so two concurrent payments at one outlet can be handed the same
--       code. The code space is only 8^6 over the alphabet "23456789", and
--       uniqueness is required only among LIVE orders — but nothing enforced
--       it.
--
-- ADDITIVE ONLY. One nullable column, one new table, one partial unique index.
-- No existing column is altered, no row is read or written.
--
-- ============================================================================
-- menu_items.stock_remaining — NULL MEANS UNTRACKED
-- ============================================================================
-- NULL for every existing row, and that is the whole safety story: an item
-- with NULL stock is never decremented, never blocks an order, and behaves
-- exactly as it does today. A restaurant opts in per dish by setting a number.
--
-- CHECK (>= 0) rather than relying on application logic, because the
-- decrement is the thing being protected. The reservation UPDATE is
--
--     UPDATE menu_items SET stock_remaining = stock_remaining - :q
--      WHERE id = :id AND stock_remaining >= :q
--
-- whose WHERE clause is what makes it safe under concurrency: Postgres
-- serialises the row write, so of two racing transactions exactly one sees a
-- sufficient value and the other matches 0 rows and is refused. The CHECK is
-- the backstop that turns a future weakening of that WHERE clause into an
-- error rather than negative stock.
--
-- ============================================================================
-- stock_reservations — why a table and not just the decrement
-- ============================================================================
-- The decrement alone cannot answer "give it back". An order that is abandoned
-- unpaid, rejected, acceptance-expired or whose payment fails has to return
-- its units, and doing that from the order's line items would double-release
-- on a retry. A row per (order, item) with an explicit state makes release
-- idempotent: you can only release what is still HELD.
--
--   HELD      — taken at order creation, before payment
--   COMMITTED — payment landed; the units are gone for good
--   RELEASED  — returned to stock
--
-- expires_at exists so unpaid HELD rows can be swept. The 45-minute pickup TTL
-- does NOT cover them: _LIVE_STATUSES is {PAID, RECEIVED, PREPARING, READY},
-- so an unpaid order is never touched by that sweeper.
--
--   !! OPEN DECISION — the TTL VALUE IS NOT SET BY THIS MIGRATION.
--   !!
--   !! This was specified as "the existing payment-retry grace window", and
--   !! NO SUCH WINDOW EXISTS in the code. What exists is:
--   !!   * CarevoService.COMPLETED_GRACE = 30 minutes — how long a VERIFIED
--   !!     PICKUP lingers in the owner queue. Nothing to do with payment.
--   !!   * AppConfig.coldRetryTimeout = 60 seconds — a cold-start HTTP retry
--   !!     timeout in customer_app. Not an order clock.
--   !!   * customer_app payment retry reopens the SAME payment session
--   !!     (pickup_screen.dart:64,1201) and has no expiry of its own.
--   !!   * no sweeper for CREATED/PENDING orders anywhere.
--   !!
--   !! So there is nothing to inherit and nothing to avoid shortening. The
--   !! column is created NOT NULL so a reservation can never be written
--   !! without a deadline, and the value is left to a config setting chosen
--   !! deliberately rather than guessed here.
--
-- ON DELETE CASCADE from customer_orders: a deleted order's reservations are
-- meaningless. Note order_events has an append-only trigger and customer_orders
-- is RESTRICT-referenced, so order deletion is effectively impossible in prod
-- anyway — the cascade is correctness, not a routine path.
--
-- ============================================================================
-- the partial UNIQUE index on (outlet_id, pickup_code)
-- ============================================================================
-- Mirrors _generate_pickup_code's own predicate exactly: unique among orders
-- that are neither COMPLETED, CANCELLED nor ABANDONED, and only where a code
-- has actually been issued. Scoped per OUTLET, not globally, because the code
-- is read aloud at one counter — two outlets may safely hold the same one.
--
-- Deliberately a partial index rather than a table constraint: a plain UNIQUE
-- would forbid ever reusing a code after an order finished, which would burn
-- through a 262,144-value space and break the existing "an expired order's
-- code is immediately reusable" behaviour that _expire_stale_pickups relies on.
--
--   !! THIS INDEX CAN FAIL TO BUILD on a database that already contains a
--   !! duplicate. Run the pre-check in the report (or below) in the Neon
--   !! console FIRST. On carevo_test it returned zero rows.
--
--   SELECT outlet_id, pickup_code, count(*) AS n,
--          array_agg(id) AS order_ids
--     FROM customer_orders
--    WHERE pickup_code IS NOT NULL
--      AND status NOT IN ('COMPLETED', 'CANCELLED', 'ABANDONED')
--    GROUP BY outlet_id, pickup_code
--   HAVING count(*) > 1
--    ORDER BY n DESC;
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   DROP INDEX IF EXISTS customer_orders_live_pickup_code_uidx;
--   DROP TABLE IF EXISTS stock_reservations;
--   ALTER TABLE menu_items DROP COLUMN stock_remaining;
--
-- Clean while stock is untracked everywhere. Once a restaurant has set real
-- numbers, dropping the column loses them.

ALTER TABLE menu_items
    ADD COLUMN IF NOT EXISTS stock_remaining integer NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_menu_items_stock_remaining'
    ) THEN
        ALTER TABLE menu_items
            ADD CONSTRAINT ck_menu_items_stock_remaining
            CHECK (stock_remaining IS NULL OR stock_remaining >= 0);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS stock_reservations (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      uuid NOT NULL REFERENCES customer_orders(id) ON DELETE CASCADE,
    menu_item_id  uuid NOT NULL REFERENCES menu_items(id),
    qty           integer NOT NULL,
    state         text    NOT NULL DEFAULT 'HELD',
    expires_at    timestamptz NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_stock_reservations_qty   CHECK (qty > 0),
    CONSTRAINT ck_stock_reservations_state
        CHECK (state IN ('HELD', 'COMMITTED', 'RELEASED'))
);

-- One reservation row per (order, item). Reserving the same dish twice on one
-- order is a bug, not a second row — quantities are summed before the UPDATE.
CREATE UNIQUE INDEX IF NOT EXISTS stock_reservations_order_item_uidx
    ON stock_reservations (order_id, menu_item_id);

-- The release sweeper's working set: HELD rows past their deadline.
CREATE INDEX IF NOT EXISTS stock_reservations_expiry_idx
    ON stock_reservations (expires_at)
    WHERE state = 'HELD';

-- Lookup by order, for commit/release on a payment or cancellation.
CREATE INDEX IF NOT EXISTS stock_reservations_order_idx
    ON stock_reservations (order_id);

-- The collision guard. Predicate matches _generate_pickup_code exactly.
CREATE UNIQUE INDEX IF NOT EXISTS customer_orders_live_pickup_code_uidx
    ON customer_orders (outlet_id, pickup_code)
    WHERE pickup_code IS NOT NULL
      AND status NOT IN ('COMPLETED', 'CANCELLED', 'ABANDONED');

COMMENT ON COLUMN menu_items.stock_remaining IS
    'Units left today. NULL = UNTRACKED, which is every existing row: such an '
    'item is never decremented and never blocks an order. Decremented by a '
    'conditional UPDATE (WHERE stock_remaining >= :q) whose WHERE clause is '
    'what makes concurrent orders safe; the CHECK (>= 0) is the backstop.';

COMMENT ON TABLE stock_reservations IS
    'Per-(order,item) hold taken at order creation, BEFORE payment. Exists so '
    'release is idempotent — you can only release what is still HELD — which a '
    'bare decrement on menu_items could not give. HELD -> COMMITTED on '
    'payment, HELD -> RELEASED on cancel/reject/expiry/abandon/payment-failure.';

COMMENT ON COLUMN stock_reservations.expires_at IS
    'Deadline for an UNPAID hold. NOT NULL so a reservation cannot exist '
    'without one. The 45-minute pickup TTL does not cover these: '
    '_LIVE_STATUSES is {PAID,RECEIVED,PREPARING,READY}, so an unpaid order is '
    'never swept by it. The TTL VALUE is an open decision — the "existing '
    'payment-retry grace window" it was meant to inherit does not exist in '
    'the code (see the migration header).';

COMMENT ON INDEX customer_orders_live_pickup_code_uidx IS
    'Makes a pickup code unique among LIVE orders at one outlet, which '
    '_generate_pickup_code only ever checked non-atomically (SELECT then '
    'INSERT, no lock, 8^6 space). Partial, not a plain UNIQUE: codes MUST stay '
    'reusable once an order is COMPLETED/CANCELLED/ABANDONED, which '
    '_expire_stale_pickups depends on.';
