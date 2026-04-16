import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]

async def fix():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as c:
        await c.execute(text(
            "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ))
        print("Added created_at column to order_items")
        # Verify
        r = await c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='order_items' ORDER BY ordinal_position"
        ))
        print("Columns:", [row[0] for row in r])
    await engine.dispose()

asyncio.run(fix())
