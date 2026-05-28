"""
Gusto POS - SQLAlchemy ORM Models (v2.0)
Matches DDL exactly. All relationships use lazy="raise" to catch
accidental synchronous lazy-loads at development time (not in production).
Use selectinload() / joinedload() explicitly in every query.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    UUID, Boolean, Column, DateTime, ForeignKey,
    Integer, Numeric, String, Text, Date, JSON, SERIAL
)
from sqlalchemy.orm import relationship

from app.models.base import Base


def new_uuid():
    return uuid.uuid4()


# ─────────────────────────────────────────────
# 1. IDENTITY & ACCESS MANAGEMENT
# ─────────────────────────────────────────────

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name = Column(String(100), nullable=False)
    gst_number = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    outlets = relationship("Outlet", back_populates="organization", lazy="raise")


class Outlet(Base):
    __tablename__ = "outlets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    location_name = Column(String(100), nullable=False)
    city = Column(String(50))
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    geofence_radius_meters = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="outlets", lazy="raise")
    menus = relationship("Menu", back_populates="outlet", lazy="raise")
    tables = relationship("Table", back_populates="outlet", lazy="raise")
    orders = relationship("Order", back_populates="outlet", lazy="raise")
    users = relationship("User", back_populates="outlet", lazy="raise")
    inventory = relationship("Inventory", back_populates="outlet", lazy="raise")
    sync_logs = relationship("SyncLog", back_populates="outlet", lazy="raise")
    daily_sales = relationship("DailySalesSummary", back_populates="outlet", lazy="raise")


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    permissions = Column(JSON, default=dict)

    user_roles = relationship("UserRole", back_populates="role", lazy="raise")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="users", lazy="raise")
    user_roles = relationship("UserRole", back_populates="user", lazy="raise")
    audit_logs = relationship("AuditLog", back_populates="user", lazy="raise")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)

    user = relationship("User", back_populates="user_roles", lazy="raise")
    role = relationship("Role", back_populates="user_roles", lazy="raise")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name = Column(String(100))
    phone_number = Column(String(20), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="customer", lazy="raise")


class OtpValidation(Base):
    __tablename__ = "otp_validations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone_number = Column(String(20), nullable=False)
    otp_code = Column(String(10), nullable=False)
    expiry_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────
# 2. MENU & PRODUCT ENGINE
# ─────────────────────────────────────────────

class Menu(Base):
    __tablename__ = "menus"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"))
    version_label = Column(String(50))
    is_latest = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="menus", lazy="raise")
    categories = relationship("Category", back_populates="menu", lazy="raise")


class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    menu_id = Column(UUID(as_uuid=True), ForeignKey("menus.id", ondelete="CASCADE"))
    name = Column(String(50), nullable=False)

    menu = relationship("Menu", back_populates="categories", lazy="raise")
    menu_items = relationship("MenuItem", back_populates="category", lazy="raise")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)
    short_code = Column(String(20))
    base_price = Column(Numeric(10, 2), nullable=False)
    is_veg = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)

    category = relationship("Category", back_populates="menu_items", lazy="raise")
    item_modifiers = relationship("ItemModifier", back_populates="menu_item", lazy="raise")
    order_items = relationship("OrderItem", back_populates="menu_item", lazy="raise")
    menu_history = relationship("MenuHistory", back_populates="menu_item", lazy="raise")


class ItemModifier(Base):
    __tablename__ = "item_modifiers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    menu_item_id = Column(UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"))
    modifier_name = Column(String(50), nullable=False)
    extra_price = Column(Numeric(10, 2), default=Decimal("0.00"))

    menu_item = relationship("MenuItem", back_populates="item_modifiers", lazy="raise")


class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    sku = Column(String(50), unique=True)
    name = Column(String(100))
    stock_qty = Column(Numeric(10, 2), default=Decimal("0.00"))
    unit = Column(String(20))

    inventory = relationship("Inventory", back_populates="product", lazy="raise")


class MenuHistory(Base):
    __tablename__ = "menu_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    menu_item_id = Column(UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True)
    item_name = Column(String(100))
    old_price = Column(Numeric(10, 2))
    operation_type = Column(String(20))
    changed_at = Column(DateTime, default=datetime.utcnow)

    menu_item = relationship("MenuItem", back_populates="menu_history", lazy="raise")


# ─────────────────────────────────────────────
# 3. SALES & TRANSACTIONS
# ─────────────────────────────────────────────

class Table(Base):
    __tablename__ = "tables"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"))
    table_number = Column(String(10), nullable=False)
    status = Column(Integer, default=0)  # 0=Free, 1=Occupied
    created_at = Column(DateTime, default=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="tables", lazy="raise")
    orders = relationship("Order", back_populates="table", lazy="raise")


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    readable_id = Column(Integer, autoincrement=True)  # SERIAL in DDL
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id"))
    table_id = Column(UUID(as_uuid=True), ForeignKey("tables.id"), nullable=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    total_amount = Column(Numeric(10, 2), default=Decimal("0.00"))
    order_status = Column(String(20), default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="orders", lazy="raise")
    table = relationship("Table", back_populates="orders", lazy="raise")
    customer = relationship("Customer", back_populates="orders", lazy="raise")
    order_items = relationship("OrderItem", back_populates="order", lazy="raise")
    payments = relationship("Payment", back_populates="order", lazy="raise")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"))
    menu_item_id = Column(UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=True)
    name_snap = Column(String(100))
    price_snap = Column(Numeric(10, 2))
    quantity = Column(Integer, default=1)

    order = relationship("Order", back_populates="order_items", lazy="raise")
    menu_item = relationship("MenuItem", back_populates="order_items", lazy="raise")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"))
    amount = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(String(20))
    payment_status = Column(String(20), default="Completed")
    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="payments", lazy="raise")


# ─────────────────────────────────────────────
# 4. SYSTEM & LOGS
# ─────────────────────────────────────────────

class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id", ondelete="CASCADE"))
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"))
    current_stock = Column(Numeric(10, 2), default=Decimal("0.00"))
    last_updated = Column(DateTime, default=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="inventory", lazy="raise")
    product = relationship("Product", back_populates="inventory", lazy="raise")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(Text, nullable=False)
    table_name = Column(String(50))
    ref_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="audit_logs", lazy="raise")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id"))
    sync_type = Column(String(20))
    status = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="sync_logs", lazy="raise")


class DailySalesSummary(Base):
    __tablename__ = "daily_sales_summary"

    id = Column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("outlets.id"))
    sales_date = Column(Date, nullable=False)
    total_revenue = Column(Numeric(12, 2), default=Decimal("0.00"))
    order_count = Column(Integer, default=0)

    outlet = relationship("Outlet", back_populates="daily_sales", lazy="raise")
