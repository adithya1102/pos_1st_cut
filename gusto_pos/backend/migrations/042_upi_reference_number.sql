-- 042_upi_reference_number.sql
--
-- One additive column on customer_orders for the 12-digit UPI reference
-- number (the "UTR") the CUSTOMER reads out of their own UPI app and types
-- into the pay screen.
--
-- THIS IS STILL NOT A PAYMENT CONFIRMATION, and the naming stays deliberate
-- for the same reason payment_claimed_at is not called paid_at: a reference
-- number is something the customer asserts, not something CareVo verified.
-- CareVo is not in the payment path and cannot ask any bank whether this UTR
-- exists or what it moved. What the number buys is the one thing the owner
-- was missing: a string they can search for in their own UPI app or bank
-- statement to settle "did this money arrive" in seconds instead of matching
-- on amount-plus-timestamp. Migration 035 gave the owner the order reference
-- (short_order_number, carried in the intent's `tn=`); this gives them the
-- bank's own identifier for the transfer.
--
-- ============================================================================
-- WHAT THIS DOES AND DOES NOT DO
-- ============================================================================
-- ADD COLUMN IF NOT EXISTS ... NULL. Every existing row gets NULL; no
-- existing row is UPDATEd, and no existing query that does not name this
-- column changes behaviour. Every order placed before this ships, and every
-- order placed afterwards by an app build that does not send the field,
-- keeps a NULL here -- which is exactly what the owner app renders as
-- "no UPI ref shown".
--
-- CRITICALLY, the column is NULLABLE AND MUST STAY SO. The live customer
-- builds (1.0.1 and 1.0.2+8) call POST /customer/orders/{id}/claim-paid with
-- no request body at all. Those claims are still valid claims and must still
-- succeed; they simply leave this column NULL. A NOT NULL here would break
-- every phone already in the Play Store.
--
-- ============================================================================
-- THE TWO CONSTRAINTS, AND WHY EACH ONE
-- ============================================================================
-- ck_customer_orders_upi_reference_format -- NULL or exactly 12 digits.
-- The API validates the same rule and returns 422, so this is the backstop
-- rather than the front door: it is what stops a future script, a manual
-- UPDATE, or a second writer from putting a 10-digit number or a formatted
-- string in a column whose whole value is being searchable verbatim in a
-- bank app. varchar(12) alone would still accept 'abc' and ''.
--
-- Written as an ordinary VALIDATED constraint rather than NOT VALID (the
-- shape 029 used): the unique index below is a non-CONCURRENT build that
-- scans the whole table anyway, so skipping the constraint's scan would buy
-- no lock time here. The column is created NULL in the statement directly
-- above, so the scan cannot find a violating row.
--
-- ux_customer_orders_upi_reference -- a reused reference is REJECTED.
-- PARTIAL, on "IS NOT NULL", which is the only form that works: a plain
-- UNIQUE would be satisfied by many NULLs in Postgres, but spelling the
-- predicate out keeps the index small (one entry per direct-UPI order that
-- actually carried a number, not one per order in the table) and states the
-- intent at the schema level.
--
-- Why uniqueness is the right rule: a UTR identifies ONE transfer. The same
-- number arriving on a second order means one of two things, and both need
-- stopping rather than storing -- either a customer is re-using a genuine
-- old payment to claim a new order for free, or they have mistyped. The API
-- turns the conflict into a 409 and refuses to mark the order claimed.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   DROP INDEX IF EXISTS ux_customer_orders_upi_reference;
--   ALTER TABLE customer_orders
--       DROP CONSTRAINT IF EXISTS ck_customer_orders_upi_reference_format;
--   ALTER TABLE customer_orders
--       DROP COLUMN IF EXISTS upi_reference_number;
--
-- Clean at any time: nothing outside the claim-paid write and the owner
-- order payload reads this column, and dropping it returns both to their
-- pre-042 behaviour (claims with no reference, cards with no "UPI ref").

ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS upi_reference_number varchar(12) NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_customer_orders_upi_reference_format'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT ck_customer_orders_upi_reference_format
            CHECK (upi_reference_number IS NULL
                   OR upi_reference_number ~ '^[0-9]{12}$');
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_orders_upi_reference
    ON customer_orders (upi_reference_number)
    WHERE upi_reference_number IS NOT NULL;

COMMENT ON COLUMN customer_orders.upi_reference_number IS
    'The 12-digit UPI reference number (UTR) the CUSTOMER typed when they '
    'tapped "I have paid" on a direct-UPI order. NOT a verified payment -- '
    'CareVo is not in the payment path and never confirmed this number with '
    'any bank. It exists so the restaurant can search for the transfer in '
    'its own UPI app. NULL for every order that predates migration 042, for '
    'every order from an app build that sends no reference, and for every '
    'payment mode other than UPI_MANUAL. Unique where present: one UTR is '
    'one transfer, so a repeat is refused with 409 rather than stored.';
