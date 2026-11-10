-- 039_payment_events.sql
--
-- Idempotent payment-event log for the reconciliation layer (vendor-direct
-- gateways, Task 5; service-fee eligibility, Task 6). ADDITIVE ONLY.
--
-- ============================================================================
-- WHAT THIS DOES
-- ============================================================================
-- 1. CREATE TABLE IF NOT EXISTS payment_events — one row per webhook
--    delivery attempt that reached signature verification, whether it
--    passed or not. UNIQUE(provider, event_id) is the concurrency control:
--    two simultaneous deliveries of the SAME event race on this constraint,
--    and whichever commits second gets a unique-violation instead of a
--    second row — see app/modules/carevo_payments/reconciliation.py.
--    No raw card data and no customer PII is stored here — only provider
--    name, the provider's own event/payment id, a hash of the body, and our
--    own outcome/reason.
--
-- 2. Two new nullable columns on customer_orders: vendor_payment_confirmed_at
--    / vendor_payment_confirmed_amount_paise. These are a SEPARATE axis from
--    the existing CareVo-mediated payment_status/status pair — they record
--    that an order's OWN vendor-operated gateway confirmed payment directly
--    to the vendor, a path CareVo never collects, holds, or settles money
--    on (see Task 6: "payment is PAID or vendor-confirmed" cites both as
--    alternatives). Left UNMAPPED on the CustomerOrder ORM model — read and
--    written only via raw text() SQL in reconciliation.py — for the exact
--    reason carevo_customer/model.py's own comment gives for
--    requested_pickup_at/release_at: a MAPPED column would join every
--    existing SELECT against customer_orders and create a deploy-order
--    constraint (migration before code) this additive layer does not need.
--
-- ============================================================================
-- WHAT THIS DOES NOT DO
-- ============================================================================
-- Does not touch orders, payments, payment_transactions, or any existing
-- column on customer_orders. Does not change any existing query's result
-- shape (the two new columns are unmapped, so no existing SELECT * against
-- the ORM model changes).
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- See docs/ops/039_payment_events_rollback.sql. Clean at any version where
-- nothing has written to payment_events or the two new columns yet; once
-- rows exist, dropping is a deliberate data-loss decision, not a no-op.

CREATE TABLE IF NOT EXISTS payment_events (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider         varchar(30)  NOT NULL,
    event_id         varchar(200) NOT NULL,
    outlet_id        uuid         NOT NULL REFERENCES outlets(id),
    order_id         uuid         NULL REFERENCES customer_orders(id),
    body_sha256      varchar(64)  NOT NULL,
    signature_valid  boolean      NOT NULL,
    outcome          varchar(12)  NOT NULL
        CHECK (outcome IN ('APPLIED', 'DUPLICATE', 'IGNORED', 'REJECTED', 'REVIEW')),
    reason           text         NULL,
    received_at      timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT uq_payment_events_provider_event UNIQUE (provider, event_id)
);

CREATE INDEX IF NOT EXISTS ix_payment_events_order_id
    ON payment_events (order_id);

CREATE INDEX IF NOT EXISTS ix_payment_events_outcome
    ON payment_events (outcome)
    WHERE outcome = 'REVIEW';

COMMENT ON TABLE payment_events IS
    'Append-only log of verified (or signature-rejected) vendor-gateway '
    'webhook deliveries. One row per (provider, event_id); the unique '
    'constraint is the idempotency/concurrency primitive. No card data, no '
    'customer PII.';

ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS vendor_payment_confirmed_at         timestamptz NULL,
    ADD COLUMN IF NOT EXISTS vendor_payment_confirmed_amount_paise integer    NULL;

COMMENT ON COLUMN customer_orders.vendor_payment_confirmed_at IS
    'Set by app.modules.carevo_payments.reconciliation when a VENDOR-OWNED '
    'gateway webhook (Task 5) confirms this order was paid directly to the '
    'vendor. CareVo never collects or holds this money; this column only '
    'records that confirmation arrived, for service-fee eligibility '
    '(migration 041) and operational visibility. Deliberately UNMAPPED on '
    'the CustomerOrder ORM model -- read/written only via raw SQL.';
