-- 034_pay_at_pickup.sql
--
-- Pay at pickup: the customer orders, the restaurant RINGS THEM to confirm,
-- and money changes hands at the counter. Cashfree is untouched and stays in
-- the code — this is a second payment path alongside it, not a replacement.
--
-- ADDITIVE ONLY. Eleven new columns on customer_orders, three on outlets, one
-- on customers, seven CHECK constraints, three partial indexes. No existing
-- column is altered or dropped, no row is read or written.
--
-- ============================================================================
-- WHY NEW COLUMNS AND NOT NEW STATUS VALUES
-- ============================================================================
-- Same reasoning migration 032 recorded, and it has not got weaker: `status`
-- is enumerated as a CLOSED SET in five places, several of them money- or
-- security-relevant:
--
--   _PROGRESSION         = [RECEIVED, PREPARING, READY]          -- advance
--   _LIVE_STATUSES       = {PAID, RECEIVED, PREPARING, READY}    -- TTL sweeper
--   _TERMINAL_STATUSES   = {CANCELLED, COMPLETED, ABANDONED, PICKED_UP}
--   REJECTABLE_STATUSES  = {PAID, RECEIVED, PREPARING}           -- reject gate
--   COMPOSITION_LOCKED_STATUSES                                  -- item N/A
--
-- A new status value would have to be added to each of them correctly, and the
-- failure mode of missing one is SILENT. So pay-at-pickup rides on separate
-- axes — `payment_mode` and `call_state` — and an order awaiting its
-- confirmation call keeps status='CREATED', which is true: it is created, and
-- nobody has paid or accepted anything yet.
--
-- That choice has a second payoff. CREATED is absent from _LIVE_STATUSES, so
-- the deployed owner_app (which filters its queue to those four statuses
-- client-side, orders_state.dart:64-69) CANNOT RENDER a pay-at-pickup order it
-- has no buttons for. An old tablet shows nothing rather than showing a row it
-- would mishandle.
--
-- ============================================================================
-- customer_orders.payment_mode
-- ============================================================================
-- 'PREPAID' for every existing row and every future Cashfree order, which is
-- what keeps this migration inert on deploy: create_order, mark_paid,
-- auto_receive, verify_pickup and the TTL sweeper all take byte-identical
-- paths for a PREPAID order.
--
-- 'UPI_MANUAL' is RESERVED and nothing writes it. It names the dormant
-- staff-tick path that CarevoService.mark_order_paid_by_staff still implements
-- (the endpoint was removed; the service method was deliberately left in place
-- for a possible re-enable). Allowing the value now means re-enabling that
-- path later is a code change, not a migration — and, more importantly, that
-- the CHECK does not have to be dropped and recreated on a live table to do it.
--
-- ============================================================================
-- the contact snapshot: contact_name / contact_phone
-- ============================================================================
-- COPIED onto the order, not joined from customers, for three reasons:
--
--   1. The customer can rename themselves afterwards (PATCH /customer/me); the
--      restaurant needs the name as it was given at order time.
--   2. DELETE /customer/me genuinely erases the customer row. A join would
--      leave a live order with no name the restaurant still has to hand over.
--   3. It lets the contact be redacted on a schedule without touching the
--      identity the customer still signs in with.
--
-- The phone is ALWAYS the account's verified number. Nothing in this schema or
-- the code that writes it accepts a client-supplied phone: that rule already
-- exists for customers.phone_number (see UpdateMeIn, which refuses to let the
-- client assert phone or email) and a restaurant about to cook food on the
-- strength of a number is the last place to start trusting one.
--
-- ck_customer_orders_pickup_contact is what makes "a pay-at-pickup order is
-- always reachable" a database fact rather than an application convention. It
-- permits exactly one hole, contact_redacted_at IS NOT NULL, which is the
-- 30-day sweep having legitimately cleared it.
--
-- ============================================================================
-- outlets.payment_prepaid_enabled / payment_pay_at_pickup_enabled
-- ============================================================================
-- TWO BOOLEANS, not one enum, because the two capabilities are genuinely
-- independent: an outlet can offer both, and during the rollout the interesting
-- states are "prepaid only" (today), "both" (pilot), and "pickup only" (after
-- Cashfree is switched off). An enum would have to enumerate the product of
-- those, and every new payment path would widen it again.
--
-- ck_outlets_payment_method_any is the floor: an outlet with NEITHER enabled
-- can take no orders at all, which is a state no admin should be able to reach
-- by accident. The admin route refuses it with a 422 as well, but the UI is
-- never the enforcement point — a replayed request or a direct UPDATE would
-- otherwise walk straight past it.
--
-- DEFAULTS (true, false) are what make this inert: every existing outlet is
-- prepaid-only, exactly as it is today.
--
-- NOTE what these flags do NOT do: enabling prepaid cannot conjure a payment
-- gateway. PREPAID is only ever OFFERED when the flag is on AND the selected
-- gateway reports is_live, so turning Cashfree off deployment-wide removes it
-- from every outlet's list no matter what these columns say.
--
-- ============================================================================
-- outlets.call_window_s — and the hard coupling to the stock hold
-- ============================================================================
-- How long the restaurant has to answer, SEPARATE from
-- acceptance_timeout_s (032). 180 seconds is a "tap the tablet" window; a
-- phone call is not, and reusing one number for both would mean tuning either
-- one breaks the other.
--
-- THE CEILING IS 540 AND THAT IS NOT A ROUND NUMBER BY ACCIDENT.
--
-- StockService.reserve_for_order stamps every hold with
-- expires_at = now() + STOCK_HOLD_TTL_SECONDS (600 by default), and
-- sweep_expired reclaims any HELD row whose order is not yet PAID. A
-- pay-at-pickup order is NEVER payment_status='PAID' until the handover, so a
-- call window longer than the stock hold would hand the units back while the
-- customer is still waiting for the phone to ring — and the dish would read
-- "sold out" to the next customer while someone else's unconfirmed order sat
-- on it. 540 < 600 leaves a minute of headroom. There is a test that fails if
-- this relationship is ever inverted.
--
-- The other half of the fix is in the code, not here: the hold is COMMITTED at
-- accept, so once a human says yes the units stop being sweepable at all.
--
-- ============================================================================
-- customers.no_show_count
-- ============================================================================
-- Collected food that was never picked up. At 2 the customer stops being
-- offered pay-at-pickup and is asked to prepay instead — they are not locked
-- out of the product, they lose the privilege of being trusted with it.
--
-- Deliberately NOT reset by a successful collection. Somebody with two
-- no-shows has demonstrated something that one good pickup does not undo, and
-- clearing it automatically would make the limit a rolling window nobody
-- asked for. Clearing it is an explicit admin act, like refund_required.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- Purely additive, so rollback is clean at any time and loses only the new
-- data:
--
--   DROP INDEX IF EXISTS customer_orders_open_pickup_idx;
--   DROP INDEX IF EXISTS customer_orders_pickup_queue_idx;
--   DROP INDEX IF EXISTS customer_orders_contact_redaction_idx;
--   ALTER TABLE customer_orders
--       DROP COLUMN payment_mode, DROP COLUMN contact_name,
--       DROP COLUMN contact_phone, DROP COLUMN contact_redacted_at,
--       DROP COLUMN call_state, DROP COLUMN call_attempts,
--       DROP COLUMN first_call_at, DROP COLUMN collected_payment_method,
--       DROP COLUMN collected_at, DROP COLUMN collected_by,
--       DROP COLUMN no_show_at;
--   ALTER TABLE outlets
--       DROP COLUMN payment_prepaid_enabled,
--       DROP COLUMN payment_pay_at_pickup_enabled,
--       DROP COLUMN call_window_s;
--   ALTER TABLE customers DROP COLUMN no_show_count;
--
-- It stops being clean once a cash handover has been recorded: at that point
-- collected_payment_method / collected_at / collected_by are the only record
-- that money changed hands at all, and payment_transactions alone cannot say
-- WHO took it.
--
-- ============================================================================
-- NOT ORM-MAPPED, ON PURPOSE
-- ============================================================================
-- Every column below is read and written with raw text() SQL. This follows
-- migration 031 rather than 032: a MAPPED column goes into every SELECT
-- SQLAlchemy emits against the table, so shipping the code to an environment
-- where this migration has not run breaks EVERY query against customer_orders,
-- not just the one that wanted the new column. Unmapped means the deploy order
-- is not a constraint — this file and the code can go in either order.

ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS payment_mode             text NOT NULL DEFAULT 'PREPAID',
    ADD COLUMN IF NOT EXISTS contact_name             text        NULL,
    ADD COLUMN IF NOT EXISTS contact_phone            varchar(20) NULL,
    ADD COLUMN IF NOT EXISTS contact_redacted_at      timestamptz NULL,
    ADD COLUMN IF NOT EXISTS call_state               text        NULL,
    ADD COLUMN IF NOT EXISTS call_attempts            integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS first_call_at            timestamptz NULL,
    ADD COLUMN IF NOT EXISTS collected_payment_method text        NULL,
    ADD COLUMN IF NOT EXISTS collected_at             timestamptz NULL,
    ADD COLUMN IF NOT EXISTS collected_by             uuid        NULL,
    ADD COLUMN IF NOT EXISTS no_show_at               timestamptz NULL;

-- collected_by is a real FK, added separately because ADD CONSTRAINT has no
-- IF NOT EXISTS. ON DELETE SET NULL rather than CASCADE: deleting a staff
-- account must not delete the record of a handover they performed.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_customer_orders_collected_by'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT fk_customer_orders_collected_by
            FOREIGN KEY (collected_by) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

-- CHECK constraints are guarded individually, because ADD CONSTRAINT has no
-- IF NOT EXISTS in PostgreSQL and this file must stay idempotent.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customer_orders_payment_mode'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT ck_customer_orders_payment_mode
            CHECK (payment_mode IN ('PREPAID', 'PAY_AT_PICKUP', 'UPI_MANUAL'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customer_orders_call_state'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT ck_customer_orders_call_state
            CHECK (call_state IS NULL OR call_state IN
                   ('PENDING', 'CALLED', 'UNREACHABLE'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customer_orders_collected_method'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT ck_customer_orders_collected_method
            CHECK (collected_payment_method IS NULL OR collected_payment_method IN
                   ('cash', 'upi'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customer_orders_call_attempts'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT ck_customer_orders_call_attempts
            CHECK (call_attempts >= 0);
    END IF;
END $$;

-- A pay-at-pickup order must carry a phone until it is legitimately redacted.
-- Written as an implication so it says nothing at all about a PREPAID order,
-- which has no contact snapshot and must never be required to have one.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customer_orders_pickup_contact'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT ck_customer_orders_pickup_contact
            CHECK (payment_mode <> 'PAY_AT_PICKUP'
                   OR contact_phone IS NOT NULL
                   OR contact_redacted_at IS NOT NULL);
    END IF;
END $$;

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS payment_prepaid_enabled       boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS payment_pay_at_pickup_enabled boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS call_window_s                 integer NOT NULL DEFAULT 300;

-- An outlet with no payment method at all can take no orders. Enforced here
-- as well as in the admin route, because the UI is never the enforcement point.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_outlets_payment_method_any'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT ck_outlets_payment_method_any
            CHECK (payment_prepaid_enabled OR payment_pay_at_pickup_enabled);
    END IF;
END $$;

-- Ceiling 540 < STOCK_HOLD_TTL_SECONDS (600). See the header.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_outlets_call_window'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT ck_outlets_call_window
            CHECK (call_window_s BETWEEN 60 AND 540);
    END IF;
END $$;

ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS no_show_count integer NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customers_no_show_count'
    ) THEN
        ALTER TABLE customers
            ADD CONSTRAINT ck_customers_no_show_count
            CHECK (no_show_count >= 0);
    END IF;
END $$;

-- The abuse cap's working set: this customer's open unpaid pickup orders.
-- Partial, because the open set is a handful of rows against the whole table.
--
-- The terminal-status exclusion is deliberately NOT in the predicate: `status`
-- changes as the order moves, and a partial index on a mutating column means
-- every transition is an index churn. The query carries that clause instead.
CREATE INDEX IF NOT EXISTS customer_orders_open_pickup_idx
    ON customer_orders (customer_id)
    WHERE payment_mode = 'PAY_AT_PICKUP' AND payment_status <> 'PAID';

-- The owner queue's extra clause: pay-at-pickup orders still awaiting a call.
CREATE INDEX IF NOT EXISTS customer_orders_pickup_queue_idx
    ON customer_orders (outlet_id, created_at)
    WHERE payment_mode = 'PAY_AT_PICKUP' AND status = 'CREATED';

-- The redaction sweep's working set: contacts still present and not yet cleared.
CREATE INDEX IF NOT EXISTS customer_orders_contact_redaction_idx
    ON customer_orders (created_at)
    WHERE contact_phone IS NOT NULL AND contact_redacted_at IS NULL;

COMMENT ON COLUMN customer_orders.payment_mode IS
    '''PREPAID'' (default, and every existing row: paid through the gateway '
    'before the kitchen sees it), ''PAY_AT_PICKUP'' (confirmed by phone, money '
    'taken at the counter) or ''UPI_MANUAL'' (RESERVED — nothing writes it; it '
    'names the dormant staff-tick path mark_order_paid_by_staff still '
    'implements, so re-enabling that is a code change, not a migration).';

COMMENT ON COLUMN customer_orders.contact_phone IS
    'SNAPSHOT of the customer''s verified account phone, taken at order '
    'creation. Never client-supplied. Copied rather than joined so a later '
    'rename or an account deletion cannot leave the restaurant holding an '
    'order it cannot put a name to. Cleared by the 30-day redaction sweep, '
    'which stamps contact_redacted_at.';

COMMENT ON COLUMN customer_orders.call_state IS
    'NULL = not a pay-at-pickup order. ''PENDING'' (nobody has rung yet), '
    '''CALLED'' (staff logged a call), ''UNREACHABLE'' (staff could not reach '
    'them — the order is then rejected with that reason). A SEPARATE axis from '
    'both status and acceptance_state: a call is a thing a human did, not a '
    'state the order is in, and two orders with identical status can differ on '
    'whether anyone has picked up the phone.';

COMMENT ON COLUMN customer_orders.collected_by IS
    'The staff user who took the money and handed the food over. The one piece '
    'of handover accountability payment_transactions cannot carry: it records '
    'that cash arrived, not who was holding it.';

COMMENT ON COLUMN outlets.payment_pay_at_pickup_enabled IS
    'Off for every outlet until an admin turns it on, which is what makes '
    'pay-at-pickup a per-outlet pilot rather than a platform-wide switch. '
    'Being on is necessary but not sufficient: the customer must also have a '
    'verified phone, no open unpaid pickup order, and fewer than 2 no-shows.';

COMMENT ON COLUMN outlets.payment_prepaid_enabled IS
    'On by default — today''s behaviour. Being on does NOT conjure a gateway: '
    'PREPAID is only offered when this is true AND the selected gateway reports '
    'is_live, so switching Cashfree off deployment-wide removes prepaid from '
    'every outlet regardless of this column.';

COMMENT ON COLUMN outlets.call_window_s IS
    'Seconds the restaurant has to answer a pay-at-pickup order, separate from '
    'acceptance_timeout_s (a tablet tap and a phone call are not the same '
    'window). Capped at 540 because it MUST stay below '
    'STOCK_HOLD_TTL_SECONDS (600): a longer window hands the stock back while '
    'the customer is still waiting for the call.';

COMMENT ON COLUMN customers.no_show_count IS
    'Pay-at-pickup orders this customer never collected. At 2 they stop being '
    'offered pay-at-pickup and must prepay. NOT reset by a later successful '
    'pickup — clearing it is an explicit admin act.';
