from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings
from app.models.base import Base

# All model imports — required so SQLAlchemy registers every table in metadata
from app.modules.organizations.model import Organization
from app.modules.outlets.model import Outlet, Table
from app.modules.roles.model import Role
from app.modules.users.model import User, user_roles_table
from app.modules.customers.model import Customer
from app.modules.otp.model import OtpValidation
from app.modules.menu.model import Menu, MenuCategory, MenuItem, ItemModifier, MenuHistory
from app.modules.products.model import Product
from app.modules.orders.model import Order
from app.modules.order_items.model import OrderItem
from app.modules.payments.model import Payment
from app.modules.inventory.model import Inventory
from app.modules.audit_logs.model import AuditLog
from app.modules.sync_logs.model import SyncLog
from app.modules.daily_sales.model import DailySalesSummary

engine = create_async_engine(settings.DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """No-op — schema is managed by reset_db.py."""
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
