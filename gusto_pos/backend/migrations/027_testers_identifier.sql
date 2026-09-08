-- 027_testers_identifier.sql
--
-- Generalize the tester roster key from phone-only to the SAME
-- COALESCE(phone_number, email) identifier that contact_labels (026) and the
-- testing orders view already use, so a Google-only (email) tester is matched
-- exactly like a phone (OTP) one. No second convention is invented.
--
--   identifier holds a phone OR an email — whatever COALESCE(phone_number,
--     email) yields for that customer. It is the roster match key from now on.
--   phone_number is KEPT (now nullable) so historical rows and phone-based
--     display are untouched; an email-only tester leaves phone_number NULL and
--     carries the email in identifier only.
--
-- Additive, idempotent, reversible:
--   DROP INDEX testers_identifier_key;
--   ALTER TABLE testers DROP COLUMN identifier;
--   ALTER TABLE testers ALTER COLUMN phone_number SET NOT NULL;
-- The last step is clean only while no email-only row exists (such a row has a
-- NULL phone_number) — the intended one-way door once email testers are in use.

ALTER TABLE testers ADD COLUMN IF NOT EXISTS identifier varchar(255);

-- Backfill: an existing row's phone_number IS its identifier.
UPDATE testers SET identifier = phone_number
 WHERE identifier IS NULL AND phone_number IS NOT NULL;

-- phone_number is no longer the roster key and no longer required.
ALTER TABLE testers ALTER COLUMN phone_number DROP NOT NULL;

-- identifier is the key now: one roster row per identifier.
ALTER TABLE testers ALTER COLUMN identifier SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS testers_identifier_key ON testers (identifier);

COMMENT ON COLUMN testers.identifier IS
    'Roster match key = COALESCE(customers.phone_number, customers.email). Phone '
    'for OTP testers, email for Google-only testers. Same identifier convention '
    'as contact_labels (migration 026).';
