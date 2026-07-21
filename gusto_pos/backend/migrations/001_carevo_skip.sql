-- ============================================================================
-- CareVo Skip — Additive migration 001
-- Branch: 21_7 | Target: existing GustoPOS Neon DB
--
-- SAFETY CONTRACT:
--   * ADDITIVE ONLY. No DROP, no ALTER of existing columns, no data changes.
--   * Touches exactly ONE existing table (menu_items) — two new nullable/
--     defaulted columns, explicitly authorized in the brief.
--   * Everything else is CREATE TABLE IF NOT EXISTS (new isolated tables).
--   * Does NOT touch: orders, order_items, payments, customers, waiter/KDS
--     tables, or any existing working flow.
--   * Idempotent: safe to run more than once.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1) Existing table extension (the only authorized change to a live table)
-- ----------------------------------------------------------------------------
ALTER TABLE menu_items
    ADD COLUMN IF NOT EXISTS is_available      boolean NOT NULL DEFAULT true;
ALTER TABLE menu_items
    ADD COLUMN IF NOT EXISTS prep_time_minutes integer;   -- nullable; NULL = unset

-- ----------------------------------------------------------------------------
-- 2) customer_orders  (Skip pre-order/pickup order header)
--    FKs to EXISTING customers(id) and outlets(id) — reuse, no duplication.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer_orders (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id              uuid NOT NULL REFERENCES customers(id),
    outlet_id                uuid NOT NULL REFERENCES outlets(id),

    -- lifecycle: CREATED -> PAID -> RECEIVED -> PREPARING -> READY -> COMPLETED
    --            (+ PAYMENT_FAILED, CANCELLED)
    status                   varchar(20)  NOT NULL DEFAULT 'CREATED',

    total_amount             numeric(10,2) NOT NULL DEFAULT 0,
    payment_status           varchar(20)  NOT NULL DEFAULT 'PENDING',

    -- pickup verification
    pickup_code              varchar(8),                 -- generated on PAID
    failed_attempts          integer      NOT NULL DEFAULT 0,
    is_locked                boolean      NOT NULL DEFAULT false,  -- true after 3 fails
    pickup_verified_at       timestamptz,

    customer_notes           varchar(500),
    created_at               timestamptz  NOT NULL DEFAULT now(),
    updated_at               timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_customer_orders_customer ON customer_orders(customer_id);
CREATE INDEX IF NOT EXISTS ix_customer_orders_outlet   ON customer_orders(outlet_id);
CREATE INDEX IF NOT EXISTS ix_customer_orders_status   ON customer_orders(status);
-- pickup_code is unique only among live (unverified) orders per outlet:
CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_orders_pickup_live
    ON customer_orders(outlet_id, pickup_code)
    WHERE pickup_code IS NOT NULL AND status NOT IN ('COMPLETED','CANCELLED');

-- ----------------------------------------------------------------------------
-- 3) customer_order_items  (line items, price snapshotted like order_items)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer_order_items (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_order_id  uuid NOT NULL REFERENCES customer_orders(id) ON DELETE CASCADE,
    menu_item_id       uuid REFERENCES menu_items(id),   -- nullable if item later removed
    name_snap          varchar(200),
    price_snap         numeric(10,2),
    quantity           integer NOT NULL DEFAULT 1,
    customizations     jsonb,                            -- selected modifiers/options
    item_notes         varchar(300),
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_customer_order_items_order
    ON customer_order_items(customer_order_id);

-- ----------------------------------------------------------------------------
-- 4) payment_transactions  (gateway webhook records — Razorpay/Cashfree)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_transactions (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_order_id  uuid NOT NULL REFERENCES customer_orders(id) ON DELETE CASCADE,

    gateway            varchar(20)  NOT NULL,            -- 'razorpay' | 'cashfree' | 'stub'
    gateway_order_id   varchar(100),
    gateway_payment_id varchar(100),
    gateway_signature  varchar(255),

    method             varchar(20),                      -- 'upi' | 'card' | 'netbanking'
    amount             numeric(10,2) NOT NULL,
    currency           varchar(8)   NOT NULL DEFAULT 'INR',

    status             varchar(20)  NOT NULL DEFAULT 'CREATED',  -- CREATED|PAID|FAILED
    raw_payload        jsonb,                            -- full webhook body for audit
    created_at         timestamptz  NOT NULL DEFAULT now(),
    updated_at         timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_payment_tx_order
    ON payment_transactions(customer_order_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_tx_gateway_payment
    ON payment_transactions(gateway, gateway_payment_id)
    WHERE gateway_payment_id IS NOT NULL;

COMMIT;
