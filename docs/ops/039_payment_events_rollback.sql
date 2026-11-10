-- Rollback for migrations/039_payment_events.sql
--
-- Safe to run at any point BEFORE this layer is enabled in production
-- (VENDOR_GATEWAY_ENABLED stays false until Task 5's route is deployed and
-- deliberately turned on). Once real rows exist, dropping payment_events or
-- the two customer_orders columns is a deliberate data-loss decision.

DROP INDEX IF EXISTS ix_payment_events_outcome;
DROP INDEX IF EXISTS ix_payment_events_order_id;
DROP TABLE IF EXISTS payment_events;

ALTER TABLE customer_orders
    DROP COLUMN IF EXISTS vendor_payment_confirmed_at,
    DROP COLUMN IF EXISTS vendor_payment_confirmed_amount_paise;
