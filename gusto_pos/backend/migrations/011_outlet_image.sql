-- Migration 011: outlet storefront image
--
-- Additive and idempotent, same shape as 005 (upi_id) and 009 (phone_number).
-- Single change: outlets.image_url, a nullable Cloudinary URL shown on the
-- customer_app outlet card in place of the generic restaurant glyph.
--
-- Nullable with no backfill: every existing outlet has no photo, and NULL is
-- the honest representation. The customer card already renders a fallback icon,
-- so a null here is a supported state, not a missing value to be filled in.
--
-- varchar(500) matches menu_items.image_url, which stores the same kind of
-- Cloudinary delivery URL from the same unsigned-upload pipeline.

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS image_url varchar(500);
