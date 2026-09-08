-- Migration 010: loyalty points, coupons, premium trial
--
-- Additive and idempotent throughout (ADD COLUMN IF NOT EXISTS / CREATE TABLE
-- IF NOT EXISTS), so re-running is a no-op and nothing existing is rewritten.
--
-- NOTE ON SCOPE: this is the loyalty/coupon mechanic only. There is deliberately
-- NO billing, subscription, price, or payment-schedule column anywhere below.
-- `premium_until` is a plain timestamp granted by a free-trial coupon; paid
-- plans are a separate future workstream and nothing here presumes their shape.

-- 1. Running balance on the customer, plus the premium window ------------------
-- points_balance is the fast read for "can they redeem?"; point_transactions
-- below is the source of truth it must always agree with.
ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS points_balance numeric(10, 2) NOT NULL DEFAULT 0;

-- NULL = never had premium. Past timestamp = lapsed. Plan is DERIVED from this
-- (premium_until > now() -> "Premium", else "Free"); there is no plan column,
-- so there is no second place for the two to disagree.
ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS premium_until timestamptz;

-- 2. The audit trail ----------------------------------------------------------
-- Every movement of points, positive or negative, lands here. points_balance is
-- a cache of SUM(points_delta); this table is what you reconcile against when
-- they disagree.
CREATE TABLE IF NOT EXISTS point_transactions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    -- Set for accrual (which order earned it). NULL for redemptions, which are
    -- not tied to an order at the moment the points are spent.
    order_id     uuid REFERENCES customer_orders(id) ON DELETE SET NULL,
    points_delta numeric(10, 2) NOT NULL,
    reason       varchar(40) NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_point_txn_customer
    ON point_transactions (customer_id, created_at DESC);

-- Hard idempotency for accrual: an order can only ever earn points once, even
-- if mark_paid is somehow reached twice concurrently. Partial index so the many
-- NULL-order redemption rows are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS idx_point_txn_one_accrual_per_order
    ON point_transactions (order_id)
    WHERE reason = 'ORDER_ACCRUAL' AND order_id IS NOT NULL;

-- 3. Coupons ------------------------------------------------------------------
-- Net-new: the codebase had no coupon, discount, promo or voucher mechanism of
-- any kind before this migration, so there was nothing to extend.
--
-- Two kinds share one table because they share a lifecycle (issued -> single
-- redemption -> spent) and differ only in what redeeming does:
--   POINTS_DISCOUNT  -> discount_amount off one order   (Task 5)
--   PREMIUM_TRIAL    -> trial_days added to premium_until (Task 6)
CREATE TABLE IF NOT EXISTS coupons (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code              varchar(24) NOT NULL UNIQUE,
    -- NULL = a floating code not bound to one customer (acquisition mechanic:
    -- hand the same code to many people). Points-issued coupons are always bound.
    customer_id       uuid REFERENCES customers(id) ON DELETE CASCADE,
    kind              varchar(20) NOT NULL,
    discount_amount   numeric(10, 2) NOT NULL DEFAULT 0,
    trial_days        integer NOT NULL DEFAULT 0,
    -- ACTIVE -> REDEEMED. Single-use is enforced in the service by an UPDATE
    -- guarded on status = 'ACTIVE', so two concurrent redemptions cannot both win.
    status            varchar(12) NOT NULL DEFAULT 'ACTIVE',
    redeemed_order_id uuid REFERENCES customer_orders(id) ON DELETE SET NULL,
    redeemed_at       timestamptz,
    expires_at        timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coupons_kind_valid CHECK (kind IN ('POINTS_DISCOUNT', 'PREMIUM_TRIAL')),
    CONSTRAINT coupons_status_valid CHECK (status IN ('ACTIVE', 'REDEEMED', 'EXPIRED'))
);

CREATE INDEX IF NOT EXISTS idx_coupons_customer_status
    ON coupons (customer_id, status);

-- 4. Order-side record of an applied discount ---------------------------------
-- Without these, a discounted order just has a smaller total_amount and no way
-- to tell a discount from cheaper food — which also makes the accrual figure
-- unauditable after the fact.
ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS discount_amount numeric(10, 2) NOT NULL DEFAULT 0;

ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS coupon_id uuid REFERENCES coupons(id) ON DELETE SET NULL;
