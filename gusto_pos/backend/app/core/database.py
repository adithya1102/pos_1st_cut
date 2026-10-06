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

# echo was hardcoded True, which logs EVERY statement with its bound
# parameters. On Render that is the whole query stream — including customer
# phone numbers, pickup codes and token subjects — written to a log store with
# a different retention and access model than the database itself, plus a
# per-statement formatting cost on every request.
#
# Now opt-IN via SQL_ECHO (default False), so a deploy that sets nothing gets
# the quiet behaviour. Set SQL_ECHO=true locally to get the firehose back.
#
# Pool settings are deliberately untouched here: pool_size/max_overflow stay
# at the SQLAlchemy defaults (5/10) and pool_pre_ping stays on. Changing the
# pool is a capacity decision that needs its own measurement, not a drive-by.
engine = create_async_engine(
    settings.DATABASE_URL, echo=settings.SQL_ECHO, pool_pre_ping=True
)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """No-op — schema is managed by reset_db.py."""
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
