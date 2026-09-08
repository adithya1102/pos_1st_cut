-- 026_contact_labels.sql
--
-- Short-term human-readable tags for order identifiers. The app has no real
-- customer names for most orders (OTP sign-in captures only a phone; Google
-- sign-in captures an email), so a tester watching the dashboard cannot tell
-- +919812345678 from +919887654321 at a glance. This lets them attach a label
-- ("Asha's phone", "test device 2") to an identifier and see it from then on.
--
-- SEPARATE from `testers` (migration 025) on purpose: testers gates auto-pickup
-- and compliance and is a curated roster; contact_labels is a loose, editable
-- display aid that applies to ANY identifier that places an order, tester or
-- not. Merging them would make a display tweak imply auto-pickup scope.
--
-- identifier is the PRIMARY KEY (hence UNIQUE): one label per identifier, and an
-- upsert replaces it. It holds whatever identifies the order's customer — phone
-- when present, else email (COALESCE(phone_number, email) in the query). label
-- is required (an empty label is a delete, done by the app, not stored). Not a
-- permanent identity system: nothing joins customers to this, and dropping the
-- table loses only the tags.
--
-- Additive, idempotent, reversible: DROP TABLE contact_labels; restores the
-- schema. Touches no existing table.

CREATE TABLE IF NOT EXISTS contact_labels (
    identifier varchar(255) PRIMARY KEY,
    label      varchar(120) NOT NULL,
    updated_at timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE contact_labels IS
    'Short-term human-readable tags for order identifiers (migration 026). '
    'identifier = COALESCE(phone_number, email). Display aid only — NOT identity, '
    'NOT auto-pickup scope (that is testers, migration 025).';
