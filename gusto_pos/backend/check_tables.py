import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def check_tables():
    async with AsyncSessionLocal() as db:
        # Get all table names
        result = await db.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
        ))
        print("\n=== DATABASE TABLES ===")
        for row in result:
            print(f"  {row[0]}")
        
        # Check categories vs menu_categories
        print("\n=== CHECKING CATEGORIES TABLE ===")
        for tbl in ['categories', 'menu_categories']:
            try:
                result = await db.execute(text(
                    f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{tbl}' ORDER BY ordinal_position"
                ))
                rows = result.fetchall()
                if rows:
                    print(f"\nTABLE: {tbl}")
                    for r in rows:
                        print(f"  {r[0]} ({r[1]})")
            except Exception as e:
                print(f"{tbl}: ERROR {e}")

asyncio.run(check_tables())
