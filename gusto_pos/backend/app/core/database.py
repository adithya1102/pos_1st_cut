from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings
from app.models.base import Base

engine = create_async_engine(settings.DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Import all models so SQLAlchemy can register them, then create tables."""
    # Import models to ensure they are registered with SQLAlchemy
    from app.modules.organizations.model import Organization
    from app.modules.outlets.model import Outlet, Table
    from app.modules.roles.model import Role
    from app.modules.users.model import User
    from app.modules.customers.model import Customer
    from app.modules.menu.model import Menu, MenuCategory, MenuItem, ItemModifier
    from app.modules.categories.model import Category
    from app.modules.orders.model import Order
    from app.modules.order_items.model import OrderItem
    from app.modules.payments.model import Payment
    from app.modules.inventory.model import Inventory
    from app.modules.sync_logs.model import SyncLog
    from app.modules.audit_logs.model import AuditLog

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        # Log the error and continue so the app can start even if DB is unavailable
        print(f"Warning: failed to initialize database tables: {e}")



