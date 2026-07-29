-- Migration 004: dish images
--
-- Additive and idempotent. Single change: menu_items.image_url, a nullable text
-- column holding the URL of an image uploaded to external storage (e.g.
-- Cloudinary). No binaries are stored in Postgres — only the returned URL.
--
-- NOTE: is_veg and prep_time_minutes already exist on menu_items (verified in
-- prod), so this migration does NOT touch them. This is the only schema change
-- required for the Phase 1 menu-CRUD + images work.

ALTER TABLE menu_items
    ADD COLUMN IF NOT EXISTS image_url varchar(1024);
