"""
Nuclear database reset script for Gusto POS v2.0.
Drops all tables, recreates the full 21-table schema, and seeds default data.

Run from the backend/ directory:
    cd gusto_pos/backend
    python reset_db.py
"""
import asyncio
import sys
import os

# Ensure app package is importable when run directly
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.base import Base

# Register all 21 tables in Base.metadata by importing every model
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


async def drop_and_recreate(engine):
    async with engine.begin() as conn:
        print("Dropping all tables and sequences...")
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text('GRANT ALL ON SCHEMA public TO PUBLIC'))
        print("Schema wiped clean.")

        print("Creating pgcrypto extension...")
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))

        print("Creating orders_readable_id_seq...")
        await conn.execute(text("CREATE SEQUENCE IF NOT EXISTS orders_readable_id_seq"))

        print("Creating all tables from SQLAlchemy metadata...")
        await conn.run_sync(Base.metadata.create_all)
        print("All tables created.")


async def seed(engine):
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        # Seed 3 default roles
        roles = [
            Role(name="Owner",   permissions={"all": True}),
            Role(name="Manager", permissions={"reports": True, "refunds": True}),
            Role(name="Waiter",  permissions={"ordering": True}),
        ]
        session.add_all(roles)
        await session.flush()

        # Seed 1 default organization
        org = Organization(name="Gusto Restaurant Group", gst_number="29ABCDE1234F1Z5")
        session.add(org)
        await session.flush()

        # Seed 1 default outlet
        outlet = Outlet(
            organization_id=org.id,
            location_name="Main Branch",
            city="Bangalore",
            geofence_radius_meters=100,
        )
        session.add(outlet)
        await session.commit()

    print(f"Seeded:")
    print(f"  Organization : Gusto Restaurant Group")
    print(f"  Outlet       : Main Branch, Bangalore")
    print(f"  Roles        : Owner, Manager, Waiter")


async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    try:
        await drop_and_recreate(engine)
        await seed(engine)
        print("\nDatabase reset complete. Ready to go.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
