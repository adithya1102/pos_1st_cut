import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def check_all_menu_tables():
    async with AsyncSessionLocal() as db:
        for table in ['menus', 'menu_categories', 'menu_items', 'item_modifiers']:
            result = await db.execute(text(
                f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position"
            ))
            rows = result.fetchall()
            print(f"\n=== {table.upper()} ===")
            cols = [r[0] for r in rows]
            for col in cols:
                print(f"  {col}")
            if 'created_at' not in cols:
                print(f"  ❌ MISSING: created_at")

asyncio.run(check_all_menu_tables())
