import asyncio
from app.core.database import engine
from app.modules.sessions.models import CustomerSession, OtpRecord, WaiterNotification
async def run():
    async with engine.begin() as conn:
        await conn.run_sync(CustomerSession.metadata.create_all)
        await conn.run_sync(OtpRecord.metadata.create_all)
        await conn.run_sync(WaiterNotification.metadata.create_all)
    print("Session tables created!")
asyncio.run(run())
