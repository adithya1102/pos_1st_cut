"""Fix schema: rename categories -> menu_categories and add missing columns."""
import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text


async def fix():
    async with AsyncSessionLocal() as db:
        # 1. Check if menu_categories already exists
        r = await db.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name='menu_categories'")
        )
        if r.fetchone():
            print("menu_categories already exists, skipping rename")
        else:
            # Rename categories -> menu_categories
            await db.execute(text("ALTER TABLE categories RENAME TO menu_categories"))
            print("Renamed categories -> menu_categories")

        # 2. Add created_at if missing
        r = await db.execute(
            text("SELECT 1 FROM information_schema.columns WHERE table_name='menu_categories' AND column_name='created_at'")
        )
        if r.fetchone():
            print("menu_categories.created_at already exists")
        else:
            await db.execute(text("ALTER TABLE menu_categories ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
            print("Added created_at to menu_categories")

        await db.commit()
        print("Done!")


asyncio.run(fix())
