import asyncio
from app.core.database import engine
from sqlalchemy import text

async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE table_sessions ADD COLUMN IF NOT EXISTS zone VARCHAR(20) DEFAULT 'normal'"))
        print('table_sessions migration done')
        try:
            await conn.execute(text("ALTER TABLE tables ADD COLUMN IF NOT EXISTS zone VARCHAR(20) DEFAULT 'normal'"))
            print('tables migration done')
        except Exception as e:
            print(f'tables table skip: {e}')

asyncio.run(migrate())
