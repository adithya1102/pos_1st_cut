-- Migration 005: per-outlet UPI payee
--
-- Additive and idempotent. Single change: outlets.upi_id, a nullable VPA
-- (e.g. "name@bank") used as the payee (pa=) when customer_app builds a
-- upi://pay intent link. Nullable so existing outlets are unaffected; new
-- self-signups collect it as a required field at registration.

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS upi_id varchar(255);
