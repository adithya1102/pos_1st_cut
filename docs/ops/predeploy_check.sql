-- predeploy_check.sql
-- Read-only. SELECT statements only — no INSERT/UPDATE/DELETE/DDL.
-- Run against production before and after a migration apply to confirm the
-- expected schema state. Safe to run any number of times.

-- 1. Which tables introduced by migrations 039-041 exist.
SELECT
    t.table_name,
    EXISTS (
        SELECT 1 FROM information_schema.tables it
        WHERE it.table_schema = 'public' AND it.table_name = t.table_name
    ) AS exists
FROM (VALUES
    ('payment_events'),
    ('outlet_gateway_credentials'),
    ('service_fee_ledger')
) AS t(table_name);

-- 2. Which payment/gateway columns on outlets exist (migrations 034-037).
SELECT
    c.column_name,
    EXISTS (
        SELECT 1 FROM information_schema.columns ic
        WHERE ic.table_schema = 'public'
          AND ic.table_name = 'outlets'
          AND ic.column_name = c.column_name
    ) AS exists
FROM (VALUES
    ('payment_prepaid_enabled'),
    ('payment_pay_at_pickup_enabled'),
    ('payment_upi_manual_enabled'),
    ('cashfree_unlocked')
) AS c(column_name);

-- 3. Row counts of the two largest live-data tables.
SELECT 'orders' AS table_name, count(*) AS row_count FROM orders
UNION ALL
SELECT 'customers' AS table_name, count(*) AS row_count FROM customers;

-- 4. Whether the migration tracking table exists yet.
SELECT to_regclass('public.schema_migrations') IS NOT NULL AS schema_migrations_exists;
