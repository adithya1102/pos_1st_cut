-- ============================================================
-- RUDRARTHI RESTAURANT — Seed Data
-- Run after schema.sql (or after Alembic migrations)
-- Usage: psql -U postgres -d gusto_pos -f seed_rudrarthi.sql
-- ============================================================

-- Enable UUID extension (idempotent)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- STEP 1: Organization
-- ============================================================
INSERT INTO organizations (id, name, gst_number)
VALUES (
    'aaaaaaaa-0000-0000-0000-000000000001',
    'Rudrarthi Fine Dining Pvt Ltd',
    '33AAAAA0000A1Z5'
) ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- STEP 2: Outlet  (ID must match OUTLET_ID in all services)
-- ============================================================
INSERT INTO outlets (id, organization_id, location_name, city, latitude, longitude, geofence_radius_meters)
VALUES (
    '0b8a8349-6144-41a8-b028-b9089bd8eaea',
    'aaaaaaaa-0000-0000-0000-000000000001',
    'Rudrarthi — Main Branch',
    'Chennai',
    12.982713,
    80.190007,
    100
) ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- STEP 3: Roles (idempotent)
-- ============================================================
INSERT INTO roles (name, permissions) VALUES
  ('Owner',   '{"all": true}'),
  ('Manager', '{"reports": true, "refunds": true}'),
  ('Kitchen', '{"kds_view": true}'),
  ('Waiter',  '{"ordering": true}')
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- STEP 4: Menu  (is_latest = true)
-- ============================================================
INSERT INTO menus (id, outlet_id, version_label, is_latest)
VALUES (
    'dc88b6a6-129c-479f-8609-07b8525f4310',
    '0b8a8349-6144-41a8-b028-b9089bd8eaea',
    'Rudrarthi Menu v1',
    true
) ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- STEP 5: Menu Categories
-- ============================================================
INSERT INTO menu_categories (id, menu_id, name) VALUES
  ('cat-0001-0000-0000-000000000001', 'dc88b6a6-129c-479f-8609-07b8525f4310', 'Starters'),
  ('cat-0002-0000-0000-000000000002', 'dc88b6a6-129c-479f-8609-07b8525f4310', 'Main Course'),
  ('cat-0003-0000-0000-000000000003', 'dc88b6a6-129c-479f-8609-07b8525f4310', 'Breads'),
  ('cat-0004-0000-0000-000000000004', 'dc88b6a6-129c-479f-8609-07b8525f4310', 'Rice & Biryani'),
  ('cat-0005-0000-0000-000000000005', 'dc88b6a6-129c-479f-8609-07b8525f4310', 'Beverages')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- STEP 6: Menu Items
-- ============================================================
INSERT INTO menu_items (id, category_id, name, short_code, base_price, is_veg, is_active) VALUES
  -- Starters
  ('item-0001-0000-0000-000000000001', 'cat-0001-0000-0000-000000000001', 'Paneer Tikka',        'PNR-TKK', 220.00, true,  true),
  ('item-0002-0000-0000-000000000002', 'cat-0001-0000-0000-000000000001', 'Veg Spring Rolls',    'VEG-SPR', 160.00, true,  true),
  ('item-0003-0000-0000-000000000003', 'cat-0001-0000-0000-000000000001', 'Chicken 65',          'CHK-65',  240.00, false, true),
  ('item-0004-0000-0000-000000000004', 'cat-0001-0000-0000-000000000001', 'Mushroom Pepper Fry', 'MSH-PPR', 190.00, true,  true),

  -- Main Course
  ('item-0005-0000-0000-000000000005', 'cat-0002-0000-0000-000000000002', 'Dal Makhani',         'DAL-MKH', 250.00, true,  true),
  ('item-0006-0000-0000-000000000006', 'cat-0002-0000-0000-000000000002', 'Paneer Butter Masala','PNR-BTR', 280.00, true,  true),
  ('item-0007-0000-0000-000000000007', 'cat-0002-0000-0000-000000000002', 'Chicken Curry',       'CHK-CRY', 300.00, false, true),
  ('item-0008-0000-0000-000000000008', 'cat-0002-0000-0000-000000000002', 'Mixed Vegetable',     'MIX-VEG', 220.00, true,  true),

  -- Breads
  ('item-0009-0000-0000-000000000009', 'cat-0003-0000-0000-000000000003', 'Butter Naan',         'BTR-NAN',  50.00, true,  true),
  ('item-0010-0000-0000-000000000010', 'cat-0003-0000-0000-000000000003', 'Tandoori Roti',       'TAN-ROT',  35.00, true,  true),
  ('item-0011-0000-0000-000000000011', 'cat-0003-0000-0000-000000000003', 'Garlic Naan',         'GRL-NAN',  60.00, true,  true),

  -- Rice & Biryani
  ('item-0012-0000-0000-000000000012', 'cat-0004-0000-0000-000000000004', 'Veg Biryani',         'VEG-BRY', 280.00, true,  true),
  ('item-0013-0000-0000-000000000013', 'cat-0004-0000-0000-000000000004', 'Chicken Biryani',     'CHK-BRY', 320.00, false, true),
  ('item-0014-0000-0000-000000000014', 'cat-0004-0000-0000-000000000004', 'Jeera Rice',          'JRA-RCE', 150.00, true,  true),

  -- Beverages
  ('item-0015-0000-0000-000000000015', 'cat-0005-0000-0000-000000000005', 'Masala Chai',         'MSL-CHA',  60.00, true,  true),
  ('item-0016-0000-0000-000000000016', 'cat-0005-0000-0000-000000000005', 'Mango Lassi',         'MNG-LSI', 100.00, true,  true),
  ('item-0017-0000-0000-000000000017', 'cat-0005-0000-0000-000000000005', 'Fresh Lime Soda',     'LMN-SOD',  80.00, true,  true)
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- STEP 7: Price Rules (zone pricing — normal & ac)
-- The `price_rules` table links items to zones.
-- AC zone items are priced ~15% higher.
-- ============================================================
CREATE TABLE IF NOT EXISTS price_rules (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_item_id  UUID REFERENCES menu_items(id) ON DELETE CASCADE,
    zone          VARCHAR(20) NOT NULL,
    price         DECIMAL(10,2) NOT NULL,
    is_available  BOOLEAN DEFAULT true,
    UNIQUE(menu_item_id, zone)
);

INSERT INTO price_rules (menu_item_id, zone, price, is_available) VALUES
  -- Starters — normal
  ('item-0001-0000-0000-000000000001', 'normal', 220.00, true),
  ('item-0002-0000-0000-000000000002', 'normal', 160.00, true),
  ('item-0003-0000-0000-000000000003', 'normal', 240.00, true),
  ('item-0004-0000-0000-000000000004', 'normal', 190.00, true),
  -- Starters — ac
  ('item-0001-0000-0000-000000000001', 'ac',     250.00, true),
  ('item-0002-0000-0000-000000000002', 'ac',     185.00, true),
  ('item-0003-0000-0000-000000000003', 'ac',     275.00, true),
  ('item-0004-0000-0000-000000000004', 'ac',     220.00, true),

  -- Main Course — normal
  ('item-0005-0000-0000-000000000005', 'normal', 250.00, true),
  ('item-0006-0000-0000-000000000006', 'normal', 280.00, true),
  ('item-0007-0000-0000-000000000007', 'normal', 300.00, true),
  ('item-0008-0000-0000-000000000008', 'normal', 220.00, true),
  -- Main Course — ac
  ('item-0005-0000-0000-000000000005', 'ac',     285.00, true),
  ('item-0006-0000-0000-000000000006', 'ac',     320.00, true),
  ('item-0007-0000-0000-000000000007', 'ac',     345.00, true),
  ('item-0008-0000-0000-000000000008', 'ac',     255.00, true),

  -- Breads — normal
  ('item-0009-0000-0000-000000000009', 'normal',  50.00, true),
  ('item-0010-0000-0000-000000000010', 'normal',  35.00, true),
  ('item-0011-0000-0000-000000000011', 'normal',  60.00, true),
  -- Breads — ac
  ('item-0009-0000-0000-000000000009', 'ac',      60.00, true),
  ('item-0010-0000-0000-000000000010', 'ac',      40.00, true),
  ('item-0011-0000-0000-000000000011', 'ac',      70.00, true),

  -- Rice & Biryani — normal
  ('item-0012-0000-0000-000000000012', 'normal', 280.00, true),
  ('item-0013-0000-0000-000000000013', 'normal', 320.00, true),
  ('item-0014-0000-0000-000000000014', 'normal', 150.00, true),
  -- Rice & Biryani — ac
  ('item-0012-0000-0000-000000000012', 'ac',     320.00, true),
  ('item-0013-0000-0000-000000000013', 'ac',     370.00, true),
  ('item-0014-0000-0000-000000000014', 'ac',     175.00, true),

  -- Beverages — normal
  ('item-0015-0000-0000-000000000015', 'normal',  60.00, true),
  ('item-0016-0000-0000-000000000016', 'normal', 100.00, true),
  ('item-0017-0000-0000-000000000017', 'normal',  80.00, true),
  -- Beverages — ac
  ('item-0015-0000-0000-000000000015', 'ac',      70.00, true),
  ('item-0016-0000-0000-000000000016', 'ac',     115.00, true),
  ('item-0017-0000-0000-000000000017', 'ac',      95.00, true)
ON CONFLICT (menu_item_id, zone) DO NOTHING;

-- ============================================================
-- STEP 8: Item Modifiers (per-item customisation options)
-- These appear in the per-dish customisation popup.
-- Free options have extra_price = 0.
-- Paid add-ons have extra_price > 0.
-- ============================================================
INSERT INTO item_modifiers (menu_item_id, modifier_name, extra_price) VALUES
  -- Universal free options for every item
  ('item-0001-0000-0000-000000000001', 'No Ghee',       0.00),
  ('item-0001-0000-0000-000000000001', 'No Oil',        0.00),
  ('item-0001-0000-0000-000000000001', 'No Butter',     0.00),
  ('item-0001-0000-0000-000000000001', 'Less Spicy',    0.00),
  ('item-0001-0000-0000-000000000001', 'Extra Spicy',   0.00),
  ('item-0001-0000-0000-000000000001', 'Extra Cheese',  25.00),
  ('item-0001-0000-0000-000000000001', 'Extra Butter',  15.00),

  ('item-0002-0000-0000-000000000002', 'No Ghee',       0.00),
  ('item-0002-0000-0000-000000000002', 'No Oil',        0.00),
  ('item-0002-0000-0000-000000000002', 'Less Spicy',    0.00),
  ('item-0002-0000-0000-000000000002', 'Extra Spicy',   0.00),

  ('item-0003-0000-0000-000000000003', 'No Oil',        0.00),
  ('item-0003-0000-0000-000000000003', 'Less Spicy',    0.00),
  ('item-0003-0000-0000-000000000003', 'Extra Spicy',   0.00),

  ('item-0004-0000-0000-000000000004', 'No Oil',        0.00),
  ('item-0004-0000-0000-000000000004', 'Less Spicy',    0.00),
  ('item-0004-0000-0000-000000000004', 'Extra Spicy',   0.00),
  ('item-0004-0000-0000-000000000004', 'Extra Butter',  15.00),

  ('item-0005-0000-0000-000000000005', 'No Ghee',       0.00),
  ('item-0005-0000-0000-000000000005', 'No Butter',     0.00),
  ('item-0005-0000-0000-000000000005', 'Less Spicy',    0.00),
  ('item-0005-0000-0000-000000000005', 'Extra Butter',  15.00),

  ('item-0006-0000-0000-000000000006', 'No Ghee',       0.00),
  ('item-0006-0000-0000-000000000006', 'No Butter',     0.00),
  ('item-0006-0000-0000-000000000006', 'Less Spicy',    0.00),
  ('item-0006-0000-0000-000000000006', 'Extra Cheese',  25.00),
  ('item-0006-0000-0000-000000000006', 'Extra Butter',  15.00),

  ('item-0007-0000-0000-000000000007', 'No Oil',        0.00),
  ('item-0007-0000-0000-000000000007', 'Less Spicy',    0.00),
  ('item-0007-0000-0000-000000000007', 'Extra Spicy',   0.00),
  ('item-0007-0000-0000-000000000007', 'Boneless',      0.00),

  ('item-0008-0000-0000-000000000008', 'No Ghee',       0.00),
  ('item-0008-0000-0000-000000000008', 'No Oil',        0.00),
  ('item-0008-0000-0000-000000000008', 'Less Spicy',    0.00),
  ('item-0008-0000-0000-000000000008', 'Extra Spicy',   0.00),

  ('item-0009-0000-0000-000000000009', 'No Butter',     0.00),
  ('item-0009-0000-0000-000000000009', 'Extra Butter',  15.00),
  ('item-0009-0000-0000-000000000009', 'Extra Garlic',  0.00),

  ('item-0010-0000-0000-000000000010', 'No Ghee',       0.00),
  ('item-0010-0000-0000-000000000010', 'Extra Ghee',    10.00),

  ('item-0011-0000-0000-000000000011', 'No Butter',     0.00),
  ('item-0011-0000-0000-000000000011', 'Extra Butter',  15.00),

  ('item-0012-0000-0000-000000000012', 'Less Spicy',    0.00),
  ('item-0012-0000-0000-000000000012', 'Extra Spicy',   0.00),
  ('item-0012-0000-0000-000000000012', 'No Ghee',       0.00),
  ('item-0012-0000-0000-000000000012', 'Extra Raita',   30.00),

  ('item-0013-0000-0000-000000000013', 'Less Spicy',    0.00),
  ('item-0013-0000-0000-000000000013', 'Extra Spicy',   0.00),
  ('item-0013-0000-0000-000000000013', 'Extra Raita',   30.00),

  ('item-0015-0000-0000-000000000015', 'Less Ginger',   0.00),
  ('item-0015-0000-0000-000000000015', 'Extra Sweet',   0.00),
  ('item-0015-0000-0000-000000000015', 'No Sugar',      0.00),

  ('item-0016-0000-0000-000000000016', 'Less Sweet',    0.00),
  ('item-0016-0000-0000-000000000016', 'Extra Thick',   0.00),

  ('item-0017-0000-0000-000000000017', 'Less Salt',     0.00),
  ('item-0017-0000-0000-000000000017', 'Sweet',         0.00)
ON CONFLICT DO NOTHING;

-- ============================================================
-- STEP 9: Sequence for readable_id (orders table)
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS orders_readable_id_seq START 1001;

-- ============================================================
-- DONE
-- ============================================================
SELECT 'Rudrarthi seed data loaded successfully!' AS status;
