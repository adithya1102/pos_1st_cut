-- =====================================================
-- GUSTO POS - FULL DATABASE SCHEMA (v2.0)
-- Matches SQLAlchemy ORM Models Exactly
-- =====================================================

-- 1. Enable UUIDs (Required for unique IDs)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==========================================
-- LEVEL 1: ROOT ENTITIES (No Dependencies)
-- ==========================================

-- 1. ORGANIZATIONS (The Brand Owner)
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    gst_number VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. ROLES (Permissions / Security Groups) - SERIAL PK like ORM
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    permissions JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. CUSTOMERS (The People Eating)
CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100),
    phone_number VARCHAR(20) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. OTP VALIDATIONS (Temporary Login Codes)
CREATE TABLE IF NOT EXISTS otp_validations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number VARCHAR(20) NOT NULL,
    otp_code VARCHAR(10) NOT NULL,
    expiry_time TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- LEVEL 2: BRANCHES & STAFF
-- ==========================================

-- 5. OUTLETS (Restaurant Branches)
CREATE TABLE IF NOT EXISTS outlets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    location_name VARCHAR(100) NOT NULL,
    city VARCHAR(50),
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    geofence_radius_meters INTEGER DEFAULT 100,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. USERS (Staff/Employees - Links to Roles & Outlets)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    role_id INTEGER REFERENCES roles(id),
    outlet_id UUID REFERENCES outlets(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. TABLES (Physical tables inside an outlet)
CREATE TABLE IF NOT EXISTS tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id UUID REFERENCES outlets(id) ON DELETE CASCADE,
    table_number VARCHAR(10) NOT NULL,
    status INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- LEVEL 3: CATEGORIES & PRODUCTS
-- ==========================================

-- 8. CATEGORIES (Product categories)
CREATE TABLE IF NOT EXISTS categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. PRODUCTS (The actual items for sale)
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    category_id UUID REFERENCES categories(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- LEVEL 4: MENU ENGINEERING
-- ==========================================

-- 10. MENUS (Versioning wrapper)
CREATE TABLE IF NOT EXISTS menus (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id UUID REFERENCES outlets(id) ON DELETE CASCADE,
    version_label VARCHAR(50),
    is_latest BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 11. MENU CATEGORIES (e.g., "Starters")
CREATE TABLE IF NOT EXISTS menu_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_id UUID REFERENCES menus(id) ON DELETE CASCADE,
    name VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 12. MENU ITEMS (The actual food)
CREATE TABLE IF NOT EXISTS menu_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID REFERENCES menu_categories(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    short_code VARCHAR(20) UNIQUE,
    base_price DECIMAL(10, 2) NOT NULL,
    is_veg BOOLEAN DEFAULT true,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 13. ITEM MODIFIERS (Add-ons like "Extra Cheese")
CREATE TABLE IF NOT EXISTS item_modifiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_item_id UUID REFERENCES menu_items(id) ON DELETE CASCADE,
    modifier_name VARCHAR(50) NOT NULL,
    extra_price DECIMAL(10, 2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 14. MENU HISTORY (Audit log for prices)
CREATE TABLE IF NOT EXISTS menu_history (
    id SERIAL PRIMARY KEY,
    menu_item_id UUID REFERENCES menu_items(id),
    item_name VARCHAR(100),
    base_price DECIMAL(10, 2),
    operation_type VARCHAR(20),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- LEVEL 5: INVENTORY & TRACKING
-- ==========================================

-- 15. INVENTORY (Stock tracking)
CREATE TABLE IF NOT EXISTS inventory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL,
    quantity INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- LEVEL 6: TRANSACTIONS (ORDERS)
-- ==========================================

-- 16. ORDERS (The Bill Header)
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    readable_id SERIAL,
    outlet_id UUID REFERENCES outlets(id) NOT NULL,
    table_id UUID REFERENCES tables(id),
    customer_id UUID REFERENCES customers(id),
    total_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    order_status VARCHAR(20) DEFAULT 'pending',
    kitchen_token VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 17. ORDER ITEMS (The individual dishes in a bill)
CREATE TABLE IF NOT EXISTS order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE NOT NULL,
    product_id UUID REFERENCES products(id),
    quantity INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- LEVEL 7: PAYMENTS
-- ==========================================

-- 18. PAYMENTS (Payment records)
CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID REFERENCES orders(id),
    amount DECIMAL(10, 2),
    payment_method VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- LEVEL 8: AUDIT & SYNC
-- ==========================================

-- 19. AUDIT LOGS
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action VARCHAR(100),
    meta JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 20. SYNC LOGS
CREATE TABLE IF NOT EXISTS sync_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(100),
    payload JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 21. DAILY SALES SUMMARY (For fast reporting)
CREATE TABLE IF NOT EXISTS daily_sales_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id UUID REFERENCES outlets(id),
    sales_date DATE NOT NULL,
    total_revenue DECIMAL(12, 2) DEFAULT 0.00,
    order_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(outlet_id, sales_date)
);

-- ==========================================
-- ADD RELATIONSHIPS (Back-references for ORM)
-- ==========================================

-- Add back_populates for models
ALTER TABLE roles ADD COLUMN IF NOT EXISTS users_count INTEGER DEFAULT 0;
ALTER TABLE outlets ADD COLUMN IF NOT EXISTS staff_count INTEGER DEFAULT 0;

-- ==========================================
-- SEED DATA (Default Roles)
-- ==========================================
INSERT INTO roles (name, permissions) VALUES 
('Owner', '{"all": true}'),
('Manager', '{"reports": true, "refunds": true}'),
('Kitchen', '{"kds_view": true}'),
('Waiter', '{"ordering": true}')
ON CONFLICT (name) DO NOTHING;
