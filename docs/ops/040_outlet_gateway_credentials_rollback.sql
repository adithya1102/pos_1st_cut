-- Rollback for migrations/040_outlet_gateway_credentials.sql
--
-- Safe before VENDOR_GATEWAY_ENABLED is ever turned on anywhere. Once a real
-- outlet has a credential row, dropping this table is a deliberate decision
-- to discard that outlet's webhook secret (it would need to be re-entered by
-- an admin after re-creating the table).

DROP TABLE IF EXISTS outlet_gateway_credentials;
