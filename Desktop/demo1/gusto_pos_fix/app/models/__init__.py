# Import all models here so Alembic autogenerate sees every table.
# Never skip a model — missing imports = missing migrations.

from app.models.base import Base
from app.models.models import (
    Organization,
    Outlet,
    Role,
    User,
    UserRole,
    Customer,
    OtpValidation,
    Menu,
    Category,
    MenuItem,
    ItemModifier,
    Product,
    MenuHistory,
    Table,
    Order,
    OrderItem,
    Payment,
    Inventory,
    AuditLog,
    SyncLog,
    DailySalesSummary,
)

__all__ = [
    "Base",
    "Organization", "Outlet", "Role", "User", "UserRole",
    "Customer", "OtpValidation",
    "Menu", "Category", "MenuItem", "ItemModifier", "Product", "MenuHistory",
    "Table", "Order", "OrderItem", "Payment",
    "Inventory", "AuditLog", "SyncLog", "DailySalesSummary",
]
