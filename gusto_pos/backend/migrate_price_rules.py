"""Migration: Create price_rules table and populate from menu_items."""
import asyncio
from app.core.database import engine
from sqlalchemy import text

OUTLET_ID = "0b8a8349-6144-41a8-b028-b9089bd8eaea"

async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS price_rules (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                menu_item_id UUID NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
                zone VARCHAR(20) NOT NULL DEFAULT 'normal',
                price NUMERIC(10,2) NOT NULL,
                is_available BOOLEAN DEFAULT true,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(menu_item_id, zone)
            )
            """
        ))
        # Populate Normal zone prices from existing base_price
        await conn.execute(text(
            """
            INSERT INTO price_rules (menu_item_id, zone, price, is_available)
            SELECT id, 'normal', base_price, is_active
            FROM menu_items
            ON CONFLICT (menu_item_id, zone) DO NOTHING
            """
        ))
        # Populate AC zone prices at 30% higher by default
        await conn.execute(text(
            """
            INSERT INTO price_rules (menu_item_id, zone, price, is_available)
            SELECT id, 'ac', ROUND(base_price * 1.30), is_active
            FROM menu_items
            ON CONFLICT (menu_item_id, zone) DO NOTHING
            """
        ))
        result = await conn.execute(text("SELECT count(*) FROM price_rules"))
        count = result.scalar()
        print(f"price_rules table created and populated — {count} rows")

asyncio.run(migrate())
