import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as db:
        # Check orders table columns
        r = await db.execute(text(
            "SELECT column_name, data_type, column_default, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'orders' "
            "ORDER BY ordinal_position"
        ))
        print("=== ORDERS TABLE ===")
        for row in r:
            print(f"  {row[0]:20s} {row[1]:20s} default={row[2]}  nullable={row[3]}")

        # Check if orderstatus enum type exists
        r2 = await db.execute(text(
            "SELECT typname FROM pg_type WHERE typname LIKE '%order%' OR typname LIKE '%status%'"
        ))
        print("\n=== ENUM TYPES ===")
        for row in r2:
            print(f"  {row[0]}")

asyncio.run(check())
