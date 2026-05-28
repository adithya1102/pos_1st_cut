"""
Gusto POS — Unified SQLAlchemy ORM Models v3.0
===============================================
Single-file model registry matching schema.sql exactly.

Rules:
  • lazy="raise" on all relationships — forces explicit eager loading.
  • expire_on_commit=False on the session factory — safe attribute access after commit.
  • Use selectinload() / joinedload() in every query that accesses relationships.
"""

import uuid
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    UUID, Boolean, Column, DateTime, Date, ForeignKey,
    Integer, Numeric, String, Text, JSON, UniqueConstraint,
    CheckConstraint, Index, Sequence, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, DeclarativeBase


# ── Base ─────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared base: every table gets id + created_at unless overridden."""
    pass


def _new_uuid():
    return uuid.uuid4()


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 1 — ROOT ENTITIES
# ═════════════════════════════════════════════════════════════════════════════

class Organization(Base):
    __tablename__ = "organizations"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name            = Column(String(100), nullable=False)
    gst_number      = Column(String(20))
    logo_url        = Column(Text)
    contact_email   = Column(String(100))
    contact_phone   = Column(String(20))
    address         = Column(Text)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at      = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    outlets = relationship("Outlet", back_populates="organization", lazy="raise")


class Role(Base):
    __tablename__ = "roles"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(50), unique=True, nullable=False)
    permissions = Column(JSONB, default=dict)
    created_at  = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    user_roles = relationship("UserRole", back_populates="role", lazy="raise")


class Customer(Base):
    __tablename__ = "customers"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name         = Column(String(100))
    phone_number = Column(String(20), unique=True, nullable=False)
    email        = Column(String(100))
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at   = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    orders            = relationship("Order", back_populates="customer", lazy="raise")
    customer_sessions = relationship("CustomerSession", back_populates="customer", lazy="raise")


class Product(Base):
    __tablename__ = "products"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    sku           = Column(String(50), unique=True)
    name          = Column(String(100), nullable=False)
    stock_qty     = Column(Numeric(10, 2), default=Decimal("0.00"))
    unit          = Column(String(20))
    reorder_level = Column(Numeric(10, 2), default=Decimal("0.00"))
    created_at    = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at    = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    inventory = relationship("Inventory", back_populates="product", lazy="raise")


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 2 — OUTLETS & STAFF
# ═════════════════════════════════════════════════════════════════════════════

class Outlet(Base):
    __tablename__ = "outlets"

    id                     = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    organization_id        = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    location_name          = Column(String(100), nullable=False)
    city                   = Column(String(50))
    address                = Column(Text)
    latitude               = Column(Numeric(10, 8))
    longitude              = Column(Numeric(11, 8))
    geofence_radius_meters = Column(Integer, default=100)
    timezone               = Column(String(50), default="Asia/Kolkata")
    is_active              = Column(Boolean, default=True)
    created_at             = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at             = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    organization    = relationship("Organization", back_populates="outlets", lazy="raise")
    users           = relationship("User", back_populates="outlet", lazy="raise")
    tables          = relationship("Table", back_populates="outlet", lazy="raise")
    menus           = relationship("Menu", back_populates="outlet", lazy="raise")
    orders          = relationship("Order", back_populates="outlet", lazy="raise")
    inventory       = relationship("Inventory", back_populates="outlet", lazy="raise")
    table_sessions  = relationship("TableSession", back_populates="outlet", lazy="raise")
    customer_sessions = relationship("CustomerSession", back_populates="outlet", lazy="raise")
    daily_sales     = relationship("DailySalesSummary", back_populates="outlet", lazy="raise")
    sync_logs       = relationship("SyncLog", back_populates="outlet", lazy="raise")
    notifications   = relationship("WaiterNotification", back_populates="outlet", lazy="raise")


class User(Base):
    __tablename__ = "users"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    username        = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    full_name       = Column(String(100))
    phone           = Column(String(20))
    outlet_id       = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="SET NULL"), nullable=True)
    is_active       = Column(Boolean, default=True)
    last_login_at   = Column(DateTime(timezone=True))
    created_at      = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at      = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    outlet         = relationship("Outlet", back_populates="users", lazy="raise")
    user_roles     = relationship("UserRole", back_populates="user", lazy="raise")
    audit_logs     = relationship("AuditLog", back_populates="user", lazy="raise")
    refresh_tokens = relationship("RefreshToken", back_populates="user", lazy="raise")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)

    # relationships
    user = relationship("User", back_populates="user_roles", lazy="raise")
    role = relationship("Role", back_populates="user_roles", lazy="raise")


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 3 — TABLE MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

class Table(Base):
    __tablename__ = "tables"
    __table_args__ = (
        UniqueConstraint("outlet_id", "table_number", name="uq_outlet_table"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    outlet_id    = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    table_number = Column(String(10), nullable=False)
    capacity     = Column(Integer, default=4)
    qr_token     = Column(String(12), unique=True, index=True)
    status       = Column(String(20), default="available")  # available | occupied | reserved | maintenance
    created_at   = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at   = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    outlet         = relationship("Outlet", back_populates="tables", lazy="raise")
    orders         = relationship("Order", back_populates="table", lazy="raise")
    table_sessions = relationship("TableSession", back_populates="table", lazy="raise")
    customer_sessions = relationship("CustomerSession", back_populates="table", lazy="raise")


class TableSession(Base):
    __tablename__ = "table_sessions"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    outlet_id  = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    table_id   = Column(UUID(as_uuid=True), ForeignKey("tables.id", ondelete="CASCADE"), nullable=False)
    token      = Column(String(8), unique=True, nullable=False, index=True)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    closed_at  = Column(DateTime(timezone=True))

    # relationships
    outlet = relationship("Outlet", back_populates="table_sessions", lazy="raise")
    table  = relationship("Table", back_populates="table_sessions", lazy="raise")


class CustomerSession(Base):
    __tablename__ = "customer_sessions"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    outlet_id           = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    table_id            = Column(UUID(as_uuid=True), ForeignKey("tables.id", ondelete="CASCADE"), nullable=False)
    customer_id         = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    login_type          = Column(String(20), default="phone")  # phone | google | guest
    customer_name       = Column(String(100))
    is_active           = Column(Boolean, default=True)
    confirmed_by_waiter = Column(Boolean, default=False)
    created_at          = Column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at          = Column(DateTime(timezone=True), nullable=False)

    # relationships
    outlet   = relationship("Outlet", back_populates="customer_sessions", lazy="raise")
    table    = relationship("Table", back_populates="customer_sessions", lazy="raise")
    customer = relationship("Customer", back_populates="customer_sessions", lazy="raise")
    notifications = relationship("WaiterNotification", back_populates="session", lazy="raise")


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 4 — MENU ENGINE
# ═════════════════════════════════════════════════════════════════════════════

class Menu(Base):
    __tablename__ = "menus"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    outlet_id     = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    version_label = Column(String(50), nullable=False)
    is_latest     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    outlet     = relationship("Outlet", back_populates="menus", lazy="raise")
    categories = relationship("MenuCategory", back_populates="menu", lazy="raise",
                              cascade="all, delete-orphan")


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    menu_id       = Column(UUID(as_uuid=True), ForeignKey("menus.id", ondelete="CASCADE"), nullable=False)
    name          = Column(String(100), nullable=False)
    display_order = Column(Integer, default=0)
    image_url     = Column(Text)
    created_at    = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    menu  = relationship("Menu", back_populates="categories", lazy="raise")
    items = relationship("MenuItem", back_populates="category", lazy="raise",
                         cascade="all, delete-orphan")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    category_id    = Column(UUID(as_uuid=True), ForeignKey("menu_categories.id", ondelete="CASCADE"), nullable=False)
    name           = Column(String(150), nullable=False)
    description    = Column(Text)
    short_code     = Column(String(20), unique=True)
    base_price     = Column(Numeric(10, 2), nullable=False)
    image_url      = Column(Text)
    is_veg         = Column(Boolean, default=True)
    is_active      = Column(Boolean, default=True)
    display_order  = Column(Integer, default=0)
    prep_time_mins = Column(Integer)
    created_at     = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at     = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    category      = relationship("MenuCategory", back_populates="items", lazy="raise")
    modifiers     = relationship("ItemModifier", back_populates="menu_item", lazy="raise",
                                 cascade="all, delete-orphan")
    order_items   = relationship("OrderItem", back_populates="menu_item", lazy="raise")
    menu_history  = relationship("MenuHistory", back_populates="menu_item", lazy="raise")


class ItemModifier(Base):
    __tablename__ = "item_modifiers"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    menu_item_id  = Column(UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False)
    modifier_name = Column(String(50), nullable=False)
    extra_price   = Column(Numeric(10, 2), default=Decimal("0.00"))
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    menu_item = relationship("MenuItem", back_populates="modifiers", lazy="raise")


class MenuHistory(Base):
    __tablename__ = "menu_history"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    menu_item_id   = Column(UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True)
    item_name      = Column(String(100))
    old_price      = Column(Numeric(10, 2))
    new_price      = Column(Numeric(10, 2))
    operation_type = Column(String(20), nullable=False)   # CREATE | UPDATE | DELETE | DEACTIVATE
    changed_by     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at     = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    menu_item = relationship("MenuItem", back_populates="menu_history", lazy="raise")


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 5 — ORDERS & TRANSACTIONS
# ═════════════════════════════════════════════════════════════════════════════

orders_readable_id_seq = Sequence("orders_readable_id_seq")


class Order(Base):
    __tablename__ = "orders"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    readable_id     = Column(Integer, orders_readable_id_seq, unique=True, nullable=False,
                             server_default=orders_readable_id_seq.next_value())
    outlet_id       = Column(UUID(as_uuid=True), ForeignKey("outlets.id"), nullable=False)
    table_id        = Column(UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True)
    customer_id     = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    order_type      = Column(String(20), default="dine_in")       # dine_in | takeaway | delivery
    subtotal        = Column(Numeric(10, 2), default=Decimal("0.00"))
    tax_amount      = Column(Numeric(10, 2), default=Decimal("0.00"))
    discount_amount = Column(Numeric(10, 2), default=Decimal("0.00"))
    total_amount    = Column(Numeric(10, 2), default=Decimal("0.00"))
    order_status    = Column(String(20), default="pending")
        # pending | confirmed | in_kitchen | ready | served | completed | cancelled | paid
    kitchen_token   = Column(String(50))
    notes           = Column(Text)
    created_at      = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at      = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    outlet     = relationship("Outlet", back_populates="orders", lazy="raise")
    table      = relationship("Table", back_populates="orders", lazy="raise")
    customer   = relationship("Customer", back_populates="orders", lazy="raise")
    items      = relationship("OrderItem", back_populates="order", lazy="raise",
                              cascade="all, delete-orphan")
    payments   = relationship("Payment", back_populates="order", lazy="raise",
                              cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    order_id      = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    menu_item_id  = Column(UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True)
    name_snap     = Column(String(100), nullable=False)
    price_snap    = Column(Numeric(10, 2), nullable=False)
    quantity      = Column(Integer, nullable=False, default=1)
    modifier_snap = Column(JSONB, default=list)    # snapshot of selected modifiers
    item_notes    = Column(Text)
    item_status   = Column(String(20), default="pending")
        # pending | preparing | ready | served | cancelled
    created_at    = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_oi_qty_positive"),
    )

    # relationships
    order     = relationship("Order", back_populates="items", lazy="raise")
    menu_item = relationship("MenuItem", back_populates="order_items", lazy="raise")


class Payment(Base):
    __tablename__ = "payments"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    order_id        = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    amount          = Column(Numeric(10, 2), nullable=False)
    payment_method  = Column(String(30), nullable=False)   # cash | upi | card | wallet | split
    payment_status  = Column(String(20), default="completed")  # pending | completed | failed | refunded
    transaction_ref = Column(String(100))
    created_at      = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    order = relationship("Order", back_populates="payments", lazy="raise")


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 6 — INVENTORY
# ═════════════════════════════════════════════════════════════════════════════

class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("outlet_id", "product_id", name="uq_inv_outlet_product"),
    )

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    outlet_id     = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    product_id    = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    current_stock = Column(Numeric(10, 2), default=Decimal("0.00"))
    last_updated  = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    outlet  = relationship("Outlet", back_populates="inventory", lazy="raise")
    product = relationship("Product", back_populates="inventory", lazy="raise")
    transactions = relationship("InventoryTransaction", back_populates="inventory", lazy="raise")


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    inventory_id    = Column(UUID(as_uuid=True), ForeignKey("inventory.id", ondelete="CASCADE"), nullable=False)
    txn_type        = Column(String(20), nullable=False)       # purchase | sale | waste | adjustment
    quantity_change = Column(Numeric(10, 2), nullable=False)   # +in, -out
    reference_note  = Column(Text)
    performed_by    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    inventory = relationship("Inventory", back_populates="transactions", lazy="raise")


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 7 — AUTH & OTP
# ═════════════════════════════════════════════════════════════════════════════

class OtpRecord(Base):
    __tablename__ = "otp_records"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    phone_number = Column(String(20), nullable=False)
    otp_code     = Column(String(10), nullable=False)
    is_used      = Column(Boolean, default=False)
    expiry_time  = Column(DateTime(timezone=True), nullable=False)
    created_at   = Column(DateTime(timezone=True), default=datetime.utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    user = relationship("User", back_populates="refresh_tokens", lazy="raise")


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 8 — NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════════

class WaiterNotification(Base):
    __tablename__ = "waiter_notifications"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    outlet_id     = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    table_id      = Column(UUID(as_uuid=True), ForeignKey("tables.id", ondelete="SET NULL"), nullable=True)
    customer_name = Column(String(100))
    customer_id   = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    order_preview = Column(Text)
    notif_type    = Column(String(30), nullable=False)
        # confirm_session | new_order | order_ready | customer_call | payment_request
    is_read       = Column(Boolean, default=False)
    is_confirmed  = Column(Boolean)
    session_id    = Column(UUID(as_uuid=True), ForeignKey("customer_sessions.id", ondelete="SET NULL"), nullable=True)
    created_at    = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    outlet  = relationship("Outlet", back_populates="notifications", lazy="raise")
    session = relationship("CustomerSession", back_populates="notifications", lazy="raise")


# ═════════════════════════════════════════════════════════════════════════════
# LEVEL 9 — REPORTING & AUDIT
# ═════════════════════════════════════════════════════════════════════════════

class DailySalesSummary(Base):
    __tablename__ = "daily_sales_summary"
    __table_args__ = (
        UniqueConstraint("outlet_id", "sales_date", name="uq_daily_sales"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    outlet_id       = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=False)
    sales_date      = Column(Date, nullable=False)
    total_revenue   = Column(Numeric(12, 2), default=Decimal("0.00"))
    tax_collected   = Column(Numeric(12, 2), default=Decimal("0.00"))
    discount_given  = Column(Numeric(12, 2), default=Decimal("0.00"))
    order_count     = Column(Integer, default=0)
    avg_order_value = Column(Numeric(10, 2), default=Decimal("0.00"))
    created_at      = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    outlet = relationship("Outlet", back_populates="daily_sales", lazy="raise")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action     = Column(String(100), nullable=False)
    table_name = Column(String(50))
    record_id  = Column(UUID(as_uuid=True))
    old_values = Column(JSONB)
    new_values = Column(JSONB)
    ip_address = Column(String(45))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # relationships
    user = relationship("User", back_populates="audit_logs", lazy="raise")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    outlet_id      = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"), nullable=True)
    sync_type      = Column(String(20), nullable=False)    # full | delta | menu | orders
    direction      = Column(String(10), default="up")      # up | down
    status         = Column(String(20), default="pending")  # pending | syncing | completed | failed
    records_synced = Column(Integer, default=0)
    error_message  = Column(Text)
    started_at     = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at   = Column(DateTime(timezone=True))

    # relationships
    outlet = relationship("Outlet", back_populates="sync_logs", lazy="raise")
