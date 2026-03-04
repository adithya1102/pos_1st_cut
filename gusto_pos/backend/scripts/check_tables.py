"""Check what tables exist in the database vs. what ORM models expect."""
import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

EXPECTED_TABLES = [
    "organizations", "outlets", "users", "roles", "customers",
    "otp_validations", "tables", "menus", "menu_categories",
    "menu_items", "item_modifiers", "menu_history", "products",
    "orders", "order_items", "payments", "inventory",
    "audit_logs", "sync_logs", "daily_sales_summary", "user_roles",
]


async def check():
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
        )
        existing = {row[0] for row in r.fetchall()}
        print("Existing tables:", sorted(existing))
        print()
        for t in EXPECTED_TABLES:
            status = "EXISTS" if t in existing else "MISSING"
            print(f"  {t}: {status}")


asyncio.run(check())
