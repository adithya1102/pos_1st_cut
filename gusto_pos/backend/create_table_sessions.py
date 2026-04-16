"""Run this once to create the table_sessions table"""
import asyncio
from app.core.database import engine
from app.modules.tables.models import TableSession
from sqlalchemy import text

async def create_table():
    async with engine.begin() as conn:
        await conn.run_sync(TableSession.metadata.create_all)
        print("✅ table_sessions table created!")

if __name__ == "__main__":
    asyncio.run(create_table())
