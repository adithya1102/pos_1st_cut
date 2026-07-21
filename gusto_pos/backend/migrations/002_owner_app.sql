-- ============================================================================
-- Gusto Owner App — Additive migration 002
-- Branch: 21_7 | Target: existing GustoPOS Neon DB (prod neondb)
--
-- SAFETY CONTRACT:
--   * ADDITIVE ONLY. No DROP, no ALTER of existing columns, no data changes.
--   * Touches exactly ONE existing table (outlets) — one new column with a
--     safe default, explicitly authorized in the brief.
--   * Idempotent: ADD COLUMN IF NOT EXISTS — safe to run more than once.
--   * Does NOT touch: customers, menu_items, customer_orders,
--     customer_order_items, payment_transactions, orders, order_items,
--     payments, or any waiter/KDS/billing table or flow.
-- ============================================================================

BEGIN;

-- outlets.is_visible controls whether an outlet appears in customer discovery
-- (GET /customer/outlets). Defaults true so ALL existing outlets remain visible
-- exactly as before this migration.
ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS is_visible boolean NOT NULL DEFAULT true;

COMMIT;
