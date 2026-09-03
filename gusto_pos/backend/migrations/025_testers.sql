-- 025_testers.sql
--
-- A roster of tester phone numbers — the SINGLE source of truth for two things:
--   * auto-pickup scope (testing_dashboard): an order whose customer's phone is
--     on this roster is auto-completed when it reaches READY, so a tester does
--     not have to be physically handed their food to close the loop;
--   * the daily order-compliance list (who did / didn't order in the rolling
--     23:00-IST window).
--
-- ONE table, not two lists: both features read the same rows, so a number added
-- here is immediately in scope for both.
--
-- phone_number is UNIQUE — a number is on the roster or it is not; adding it
-- twice is a no-op, not a second row. Stored as given (trimmed); matching
-- against customer_orders is done on the trimmed string, so the roster and the
-- customers table must agree on format (both carry the +91... form in this
-- deployment). name is optional (a label for the dashboard). added_at is for
-- display/audit only.
--
-- Additive, idempotent, reversible: DROP TABLE testers; restores the schema.
-- Touches no existing table.

CREATE TABLE IF NOT EXISTS testers (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number varchar(20) NOT NULL UNIQUE,
    name         varchar(100),
    added_at     timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE testers IS
    'Tester phone roster (migration 025). Single source of truth for '
    'testing_dashboard auto-pickup scope AND the daily compliance list. '
    'phone_number matches customer_orders -> customers.phone_number exactly.';
