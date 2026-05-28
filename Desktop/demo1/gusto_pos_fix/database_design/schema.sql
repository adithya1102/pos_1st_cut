-- =====================================================================
-- GUSTO POS — COMPLETE DATABASE SCHEMA v3.0
-- PostgreSQL 15+  |  All tables, constraints, indexes, seed data
-- =====================================================================
-- CONVENTIONS:
--   • UUIDs as primary keys (gen_random_uuid) except roles (SERIAL)
--   • created_at / updated_at on every mutable table
--   • ON DELETE CASCADE for child-of-parent ownership
--   • ON DELETE SET NULL for soft references
--   • All money columns: NUMERIC(10,2)
--   • snake_case everywhere
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =====================================================================
-- LEVEL 1 — ROOT ENTITIES (no foreign keys)
-- =====================================================================

-- 1. ORGANIZATIONS — the restaurant brand
CREATE TABLE IF NOT EXISTS organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,
    gst_number      VARCHAR(20),
    logo_url        TEXT,
    contact_email   VARCHAR(100),
    contact_phone   VARCHAR(20),
    address         TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 2. ROLES — permission groups (integer PK for simplicity)
CREATE TABLE IF NOT EXISTS roles (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(50) UNIQUE NOT NULL,
    permissions     JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 3. CUSTOMERS — diners / end users
CREATE TABLE IF NOT EXISTS customers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100),
    phone_number    VARCHAR(20) UNIQUE NOT NULL,
    email           VARCHAR(100),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 4. PRODUCTS — raw materials / SKU items for inventory tracking
CREATE TABLE IF NOT EXISTS products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku             VARCHAR(50) UNIQUE,
    name            VARCHAR(100) NOT NULL,
    stock_qty       NUMERIC(10,2) DEFAULT 0.00,
    unit            VARCHAR(20),                  -- kg, litre, piece, etc.
    reorder_level   NUMERIC(10,2) DEFAULT 0.00,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================================
-- LEVEL 2 — OUTLETS & STAFF
-- =====================================================================

-- 5. OUTLETS — physical restaurant branches
CREATE TABLE IF NOT EXISTS outlets (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    location_name           VARCHAR(100) NOT NULL,
    city                    VARCHAR(50),
    address                 TEXT,
    latitude                NUMERIC(10,8),
    longitude               NUMERIC(11,8),
    geofence_radius_meters  INTEGER DEFAULT 100,
    timezone                VARCHAR(50) DEFAULT 'Asia/Kolkata',
    is_active               BOOLEAN DEFAULT TRUE,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_outlets_org ON outlets(organization_id);

-- 6. USERS — staff / employees
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(50) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name       VARCHAR(100),
    phone           VARCHAR(20),
    outlet_id       UUID REFERENCES outlets(id) ON DELETE SET NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_users_outlet ON users(outlet_id);

-- 7. USER_ROLES — many-to-many (a user can hold multiple roles)
CREATE TABLE IF NOT EXISTS user_roles (
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- =====================================================================
-- LEVEL 3 — TABLE MANAGEMENT
-- =====================================================================

-- 8. TABLES — physical restaurant tables
CREATE TABLE IF NOT EXISTS tables (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    table_number    VARCHAR(10) NOT NULL,          -- "T-1", "T-2", etc.
    capacity        INTEGER DEFAULT 4,
    qr_token        VARCHAR(12) UNIQUE,            -- short QR code token
    status          VARCHAR(20) DEFAULT 'available',
                    -- available | occupied | reserved | maintenance
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (outlet_id, table_number)
);
CREATE INDEX idx_tables_outlet ON tables(outlet_id);
CREATE INDEX idx_tables_qr ON tables(qr_token);

-- 9. TABLE_SESSIONS — active QR-based sessions per table
CREATE TABLE IF NOT EXISTS table_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    table_id        UUID NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
    token           VARCHAR(8) UNIQUE NOT NULL,   -- short session token
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ
);
CREATE INDEX idx_tsess_active ON table_sessions(outlet_id, is_active) WHERE is_active = TRUE;

-- 10. CUSTOMER_SESSIONS — customer login sessions at a table
CREATE TABLE IF NOT EXISTS customer_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id           UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    table_id            UUID NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
    customer_id         UUID REFERENCES customers(id) ON DELETE SET NULL,
    login_type          VARCHAR(20) DEFAULT 'phone',  -- phone | google | guest
    customer_name       VARCHAR(100),
    is_active           BOOLEAN DEFAULT TRUE,
    confirmed_by_waiter BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_csess_active ON customer_sessions(outlet_id, is_active) WHERE is_active = TRUE;

-- =====================================================================
-- LEVEL 4 — MENU ENGINE
-- =====================================================================

-- 11. MENUS — versioned menu per outlet
CREATE TABLE IF NOT EXISTS menus (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    version_label   VARCHAR(50) NOT NULL,
    is_latest       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_menus_outlet ON menus(outlet_id);
-- Partial unique: only one "latest" menu per outlet
CREATE UNIQUE INDEX idx_menus_latest ON menus(outlet_id) WHERE is_latest = TRUE;

-- 12. MENU_CATEGORIES — e.g., Starters, Mains, Desserts
CREATE TABLE IF NOT EXISTS menu_categories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_id         UUID NOT NULL REFERENCES menus(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    display_order   INTEGER DEFAULT 0,
    image_url       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_mcat_menu ON menu_categories(menu_id);

-- 13. MENU_ITEMS — individual dishes
CREATE TABLE IF NOT EXISTS menu_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id     UUID NOT NULL REFERENCES menu_categories(id) ON DELETE CASCADE,
    name            VARCHAR(150) NOT NULL,
    description     TEXT,
    short_code      VARCHAR(20) UNIQUE,
    base_price      NUMERIC(10,2) NOT NULL,
    image_url       TEXT,
    is_veg          BOOLEAN DEFAULT TRUE,
    is_active       BOOLEAN DEFAULT TRUE,
    display_order   INTEGER DEFAULT 0,
    prep_time_mins  INTEGER,                      -- estimated preparation time
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_mitm_cat ON menu_items(category_id);
CREATE INDEX idx_mitm_active ON menu_items(is_active) WHERE is_active = TRUE;

-- 14. ITEM_MODIFIERS — add-ons (Extra Cheese, Spice Level, etc.)
CREATE TABLE IF NOT EXISTS item_modifiers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_item_id    UUID NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    modifier_name   VARCHAR(50) NOT NULL,
    extra_price     NUMERIC(10,2) DEFAULT 0.00,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_imod_item ON item_modifiers(menu_item_id);

-- 15. MENU_HISTORY — audit log for menu price / status changes
CREATE TABLE IF NOT EXISTS menu_history (
    id              SERIAL PRIMARY KEY,
    menu_item_id    UUID REFERENCES menu_items(id) ON DELETE SET NULL,
    item_name       VARCHAR(100),
    old_price       NUMERIC(10,2),
    new_price       NUMERIC(10,2),
    operation_type  VARCHAR(20) NOT NULL,          -- CREATE | UPDATE | DELETE | DEACTIVATE
    changed_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    changed_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================================
-- LEVEL 5 — ORDERS & TRANSACTIONS
-- =====================================================================

-- Sequence for human-readable order numbers
CREATE SEQUENCE IF NOT EXISTS orders_readable_id_seq;

-- 16. ORDERS — the bill header
CREATE TABLE IF NOT EXISTS orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    readable_id     INTEGER UNIQUE NOT NULL DEFAULT nextval('orders_readable_id_seq'),
    outlet_id       UUID NOT NULL REFERENCES outlets(id),
    table_id        UUID REFERENCES tables(id) ON DELETE SET NULL,
    customer_id     UUID REFERENCES customers(id) ON DELETE SET NULL,
    order_type      VARCHAR(20) DEFAULT 'dine_in',
                    -- dine_in | takeaway | delivery
    subtotal        NUMERIC(10,2) DEFAULT 0.00,
    tax_amount      NUMERIC(10,2) DEFAULT 0.00,
    discount_amount NUMERIC(10,2) DEFAULT 0.00,
    total_amount    NUMERIC(10,2) DEFAULT 0.00,
    order_status    VARCHAR(20) DEFAULT 'pending',
                    -- pending | confirmed | in_kitchen | ready | served | completed | cancelled | paid
    kitchen_token   VARCHAR(50),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_ord_outlet ON orders(outlet_id);
CREATE INDEX idx_ord_table ON orders(table_id);
CREATE INDEX idx_ord_cust ON orders(customer_id);
CREATE INDEX idx_ord_status ON orders(order_status);
CREATE INDEX idx_ord_created ON orders(created_at DESC);

-- 17. ORDER_ITEMS — line items (snapshot pricing so menu changes don't affect past orders)
CREATE TABLE IF NOT EXISTS order_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id    UUID REFERENCES menu_items(id) ON DELETE SET NULL,
    name_snap       VARCHAR(100) NOT NULL,         -- snapshot of item name at time of order
    price_snap      NUMERIC(10,2) NOT NULL,        -- snapshot of price at time of order
    quantity        INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    modifier_snap   JSONB DEFAULT '[]'::jsonb,     -- snapshot of selected modifiers
    item_notes      TEXT,
    item_status     VARCHAR(20) DEFAULT 'pending',
                    -- pending | preparing | ready | served | cancelled
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_oi_order ON order_items(order_id);

-- 18. PAYMENTS — payment records (supports split payments)
CREATE TABLE IF NOT EXISTS payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    amount          NUMERIC(10,2) NOT NULL,
    payment_method  VARCHAR(30) NOT NULL,
                    -- cash | upi | card | wallet | split
    payment_status  VARCHAR(20) DEFAULT 'completed',
                    -- pending | completed | failed | refunded
    transaction_ref VARCHAR(100),                  -- external txn reference (UPI ref, etc.)
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_pay_order ON payments(order_id);

-- =====================================================================
-- LEVEL 6 — INVENTORY
-- =====================================================================

-- 19. INVENTORY — stock levels per outlet per product
CREATE TABLE IF NOT EXISTS inventory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    current_stock   NUMERIC(10,2) DEFAULT 0.00,
    last_updated    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (outlet_id, product_id)
);
CREATE INDEX idx_inv_outlet ON inventory(outlet_id);

-- 20. INVENTORY_TRANSACTIONS — stock movement log
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    inventory_id    UUID NOT NULL REFERENCES inventory(id) ON DELETE CASCADE,
    txn_type        VARCHAR(20) NOT NULL,          -- purchase | sale | waste | adjustment
    quantity_change NUMERIC(10,2) NOT NULL,         -- positive = in, negative = out
    reference_note  TEXT,
    performed_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================================
-- LEVEL 7 — AUTH & OTP
-- =====================================================================

-- 21. OTP_RECORDS — one-time password for customer phone verification
CREATE TABLE IF NOT EXISTS otp_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number    VARCHAR(20) NOT NULL,
    otp_code        VARCHAR(10) NOT NULL,
    is_used         BOOLEAN DEFAULT FALSE,
    expiry_time     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_otp_phone ON otp_records(phone_number, is_used);

-- 22. REFRESH_TOKENS — JWT refresh token storage for staff auth
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    is_revoked      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_rt_user ON refresh_tokens(user_id);

-- =====================================================================
-- LEVEL 8 — NOTIFICATIONS
-- =====================================================================

-- 23. WAITER_NOTIFICATIONS — real-time alerts for waiters
CREATE TABLE IF NOT EXISTS waiter_notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    table_id        UUID REFERENCES tables(id) ON DELETE SET NULL,
    customer_name   VARCHAR(100),
    customer_id     UUID REFERENCES customers(id) ON DELETE SET NULL,
    order_preview   TEXT,
    notif_type      VARCHAR(30) NOT NULL,
                    -- confirm_session | new_order | order_ready | customer_call | payment_request
    is_read         BOOLEAN DEFAULT FALSE,
    is_confirmed    BOOLEAN,
    session_id      UUID REFERENCES customer_sessions(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_wn_outlet ON waiter_notifications(outlet_id, is_read);

-- =====================================================================
-- LEVEL 9 — REPORTING & AUDIT
-- =====================================================================

-- 24. DAILY_SALES_SUMMARY — pre-aggregated daily reporting
CREATE TABLE IF NOT EXISTS daily_sales_summary (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id       UUID NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
    sales_date      DATE NOT NULL,
    total_revenue   NUMERIC(12,2) DEFAULT 0.00,
    tax_collected   NUMERIC(12,2) DEFAULT 0.00,
    discount_given  NUMERIC(12,2) DEFAULT 0.00,
    order_count     INTEGER DEFAULT 0,
    avg_order_value NUMERIC(10,2) DEFAULT 0.00,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (outlet_id, sales_date)
);

-- 25. AUDIT_LOGS — system-wide audit trail
CREATE TABLE IF NOT EXISTS audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    action          VARCHAR(100) NOT NULL,
    table_name      VARCHAR(50),
    record_id       UUID,
    old_values      JSONB,
    new_values      JSONB,
    ip_address      VARCHAR(45),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_table ON audit_logs(table_name, record_id);
CREATE INDEX idx_audit_time ON audit_logs(created_at DESC);

-- 26. SYNC_LOGS — offline sync tracking (for POS terminals with intermittent connectivity)
CREATE TABLE IF NOT EXISTS sync_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id       UUID REFERENCES outlets(id) ON DELETE CASCADE,
    sync_type       VARCHAR(20) NOT NULL,          -- full | delta | menu | orders
    direction       VARCHAR(10) DEFAULT 'up',      -- up | down
    status          VARCHAR(20) DEFAULT 'pending',  -- pending | syncing | completed | failed
    records_synced  INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- =====================================================================
-- UPDATED_AT TRIGGERS — auto-update updated_at columns
-- =====================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'organizations', 'customers', 'products', 'outlets',
        'users', 'tables', 'menu_items', 'orders'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%s_updated_at
             BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()',
            tbl, tbl
        );
    END LOOP;
END $$;

-- =====================================================================
-- SEED DATA — default roles
-- =====================================================================

INSERT INTO roles (name, permissions) VALUES
    ('Owner',   '{"all": true}'),
    ('Manager', '{"reports": true, "refunds": true, "staff_manage": true, "inventory": true, "menu_edit": true, "orders": true, "payments": true}'),
    ('Kitchen', '{"kds_view": true, "order_status": true, "kitchen_manage": true, "inventory_view": true}'),
    ('Waiter',  '{"ordering": true, "table_manage": true, "customer_view": true, "payment_collect": true, "notifications": true, "pos_view": true}')
ON CONFLICT (name) DO NOTHING;
