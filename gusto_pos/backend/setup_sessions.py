import asyncio
from sqlalchemy import text
from app.core.database import engine
from app.modules.sessions.models import CustomerSession, OtpRecord, WaiterNotification

async def run():
    async with engine.begin() as conn:
        await conn.run_sync(CustomerSession.metadata.create_all)
        await conn.run_sync(OtpRecord.metadata.create_all)
        await conn.run_sync(WaiterNotification.metadata.create_all)
        # Add order_id and total_amount columns to waiter_notifications if they don't exist yet
        await conn.execute(text(
            "ALTER TABLE waiter_notifications ADD COLUMN IF NOT EXISTS order_id UUID"
        ))
        await conn.execute(text(
            "ALTER TABLE waiter_notifications ADD COLUMN IF NOT EXISTS total_amount DECIMAL(10,2)"
        ))
    print("Session tables created/migrated!")

asyncio.run(run())
