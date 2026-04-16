import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("SELECT count(*) FROM order_items"))
        count = r.scalar()
        print(f"order_items count: {count}")
        r2 = await db.execute(text("SELECT * FROM order_items LIMIT 3"))
        rows = r2.fetchall()
        if rows:
            print(f"columns: {r2.keys()}")
        for row in rows:
            print(dict(row._mapping))

asyncio.run(check())
