"""Add order approval/source and served-item columns."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings


async def migrate():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        statements = [
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'pos'",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS waiter_order_id UUID",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS needs_waiter_approval BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS waiter_approved_at TIMESTAMPTZ",
            "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS item_notes VARCHAR(500)",
            "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS is_served BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS served_at TIMESTAMPTZ",
        ]
        for statement in statements:
            await conn.execute(text(statement))
    await engine.dispose()
    print("Migration complete: orders.source column added.")


if __name__ == "__main__":
    asyncio.run(migrate())
