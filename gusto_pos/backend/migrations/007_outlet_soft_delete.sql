-- ============================================================================
-- Outlet soft-delete — Additive migration 007
-- Branch: 21_7 | Target: existing GustoPOS Neon DB (prod neondb)
--
-- SAFETY CONTRACT:
--   * ADDITIVE ONLY. No DROP, no ALTER of existing columns, no data changes.
--   * Touches exactly ONE existing table (outlets) — one new nullable column.
--   * Idempotent: ADD COLUMN IF NOT EXISTS — safe to run more than once.
--   * Does NOT touch order_events / order_outcome / prediction_log or any other
--     table. A deactivated outlet KEEPS all its historical order + event rows,
--     which are permanent training data for the prediction engine.
--
-- Semantics:
--   deactivated_at IS NULL      -> live outlet (normal).
--   deactivated_at IS NOT NULL  -> soft-deleted: hidden from customer discovery
--                                  (also forced is_visible=false), shown in the
--                                  admin console flagged as Deactivated, and
--                                  reversible via /admin/outlets/{id}/reactivate.
-- ============================================================================

ALTER TABLE outlets ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;

-- Partial index: the customer discovery query filters on the live set, which is
-- the overwhelming majority — keep it cheap as the deactivated set grows.
CREATE INDEX IF NOT EXISTS idx_outlets_live
    ON outlets (id) WHERE deactivated_at IS NULL;
