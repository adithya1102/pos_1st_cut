import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def check_menu_items_columns():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'menu_items' ORDER BY ordinal_position"
        ))
        rows = result.fetchall()
        print("\n=== MENU_ITEMS TABLE COLUMNS ===")
        for r in rows:
            print(f"  {r[0]} ({r[1]})")

asyncio.run(check_menu_items_columns())
