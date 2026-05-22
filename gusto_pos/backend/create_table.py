import asyncio
from app.core.database import engine
from sqlalchemy import text

async def create_table():
    async with engine.begin() as conn:
        await conn.execute(text('''
            CREATE TABLE IF NOT EXISTS price_rules (
                id UUID PRIMARY KEY,
                menu_item_id UUID,
                zone VARCHAR(50),
                price NUMERIC(10, 2),
                is_available BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            )
        '''))
        print("Successfully created price_rules table in the cloud!")

asyncio.run(create_table())
