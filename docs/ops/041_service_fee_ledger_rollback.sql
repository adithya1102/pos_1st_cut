-- Rollback for migrations/041_service_fee_ledger.sql
--
-- Safe before SERVICE_FEE_LEDGER_ENABLED is ever turned on anywhere. Once
-- real fee entries exist, dropping this table discards the fee-billing
-- audit trail -- a deliberate data-loss decision, not a routine rollback.
-- Does NOT drop carevo_reject_mutation() (migration 006 owns it and
-- order_events/prediction_log still depend on it).

DROP FUNCTION IF EXISTS verify_chain(uuid);
DROP FUNCTION IF EXISTS fn_advance_fee_entry_status(uuid, varchar, varchar);
DROP TRIGGER IF EXISTS service_fee_ledger_no_truncate ON service_fee_ledger;
DROP TRIGGER IF EXISTS service_fee_ledger_no_delete ON service_fee_ledger;
DROP TRIGGER IF EXISTS service_fee_ledger_core_immutable ON service_fee_ledger;
DROP FUNCTION IF EXISTS carevo_fee_ledger_reject_core_mutation();
DROP TRIGGER IF EXISTS service_fee_ledger_chain ON service_fee_ledger;
DROP FUNCTION IF EXISTS carevo_fee_ledger_chain();
DROP INDEX IF EXISTS ix_service_fee_ledger_billing_period;
DROP INDEX IF EXISTS ix_service_fee_ledger_outlet_created;
DROP TABLE IF EXISTS service_fee_ledger;
