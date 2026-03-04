from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.sync_logs.model import SyncLog

class SyncLogService:
    @staticmethod
    async def get_all_sync_logs(db: AsyncSession):
        result = await db.execute(select(SyncLog))
        return result.scalars().all()

    @staticmethod
    async def get_sync_log_by_id(db: AsyncSession, log_id: UUID):
        return await db.get(SyncLog, log_id)

    @staticmethod
    async def create_sync_log(db: AsyncSession, payload: dict[str, Any]):
        obj = SyncLog(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def update_sync_log(db: AsyncSession, log_id: UUID, payload: dict[str, Any]):
        obj = await db.get(SyncLog, log_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_sync_log(db: AsyncSession, log_id: UUID) -> bool:
        obj = await db.get(SyncLog, log_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True