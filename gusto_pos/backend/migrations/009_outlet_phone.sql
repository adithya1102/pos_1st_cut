-- Migration 009: outlet contact phone
--
-- Additive and idempotent, same shape as 005 (outlets.upi_id). Single change:
-- outlets.phone_number, a nullable contact number captured at owner self-signup
-- and shown to platform admins in the outlets table.
--
-- Nullable with no backfill: every outlet that existed before this migration
-- has no phone on record, and NULL is the honest representation of that. New
-- self-signups collect it, but it stays optional at the API so an owner who
-- skips the field still registers successfully.
--
-- varchar(20) matches customers.phone_number: enough for E.164 (+91XXXXXXXXXX)
-- with room for a country code, and no format is enforced at the DB level —
-- validation lives in the Pydantic schema.

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS phone_number varchar(20);
