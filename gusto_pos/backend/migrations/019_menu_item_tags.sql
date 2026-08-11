-- Migration 019: codify menu_items.tags
--
-- NOT A NEW FEATURE. This column ALREADY EXISTS in production and is already
-- read by live code — `/customer/menu` SELECTs `mi.tags` (CarevoService.get_menu)
-- and returns it as MenuItemOut.tags. It was added to prod by hand at some
-- point and never written down.
--
-- The consequence, found while building the API test suite: a database created
-- purely from this repository does NOT get the column, so `/customer/menu`
-- fails outright with `column mi.tags does not exist`. Every fresh deploy, every
-- new Neon branch, and every developer's local DB is broken for the menu
-- endpoint until someone adds it manually. This migration closes that gap.
--
-- ON PROD THIS IS A NO-OP. Verified against the live schema before writing:
--     data_type  = json      (NOT jsonb — do not "upgrade" it here; changing an
--                             existing column's type is a separate decision)
--     nullable   = YES
--     default    = none
--     populated  = 0 of 19 rows
-- The IF NOT EXISTS clause means prod keeps exactly the column it already has.

ALTER TABLE menu_items
    ADD COLUMN IF NOT EXISTS tags json;
