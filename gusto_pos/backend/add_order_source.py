"""
Migration: add source column to orders table.
Run once: python add_order_source.py
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings


async def migrate():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'customer'
        """))
    await engine.dispose()
    print("Migration complete: orders.source column added.")


if __name__ == "__main__":
    asyncio.run(migrate())
