import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def test():
    async with AsyncSessionLocal() as s:
        r = await s.execute(text('SELECT id, outlet_id, version_label FROM menus LIMIT 5'))
        rows = r.fetchall()
        print('=== menus ===')
        for row in rows:
            print(row)
        print('=== categories ===')
        r2 = await s.execute(text('SELECT id, menu_id, name FROM menu_categories LIMIT 10'))
        for row in r2.fetchall():
            print(row)
        print('=== items ===')
        r3 = await s.execute(text('SELECT id, category_id, name, base_price FROM menu_items LIMIT 10'))
        for row in r3.fetchall():
            print(row)

asyncio.run(test())
