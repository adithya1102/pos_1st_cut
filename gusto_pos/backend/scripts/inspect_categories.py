"""Inspect categories table structure and check menu_items FK."""
import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text


async def inspect():
    async with AsyncSessionLocal() as db:
        # Check categories columns
        r = await db.execute(
            text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='categories' ORDER BY ordinal_position")
        )
        print("categories table columns:")
        for row in r.fetchall():
            print(f"  {row[0]}: {row[1]}")

        # Check menu_items.category_id FK
        r = await db.execute(
            text("""
                SELECT tc.constraint_name, ccu.table_name AS foreign_table
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.table_name = 'menu_items'
                    AND tc.constraint_type = 'FOREIGN KEY'
                    AND ccu.column_name = 'id'
            """)
        )
        print("\nmenu_items FK constraints:")
        for row in r.fetchall():
            print(f"  {row[0]} -> {row[1]}")

        # Check if any rows in categories
        r = await db.execute(text("SELECT COUNT(*) FROM categories"))
        print(f"\ncategories row count: {r.fetchone()[0]}")


asyncio.run(inspect())
