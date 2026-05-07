"""Migration: Create outlet_config table and populate defaults."""
import asyncio
from app.core.database import engine
from sqlalchemy import text

OUTLET_ID = "0b8a8349-6144-41a8-b028-b9089bd8eaea"

async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS outlet_config (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                outlet_id UUID NOT NULL,
                config_key VARCHAR(100) NOT NULL,
                config_value VARCHAR(500) NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(outlet_id, config_key)
            )
            """
        ))
        # Default: 10 Normal tables, 10 AC tables
        await conn.execute(text(
            """
            INSERT INTO outlet_config (outlet_id, config_key, config_value)
            VALUES
                (:oid, 'normal_table_count', '10'),
                (:oid, 'ac_table_count', '10')
            ON CONFLICT (outlet_id, config_key) DO NOTHING
            """
        ), {"oid": OUTLET_ID})
        result = await conn.execute(text("SELECT count(*) FROM outlet_config"))
        count = result.scalar()
        print(f"outlet_config table created — {count} rows")

asyncio.run(migrate())
