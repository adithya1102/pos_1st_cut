from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.audit_logs.model import AuditLog

class AuditLogService:
    @staticmethod
    async def get_all_audit_logs(db: AsyncSession):
        result = await db.execute(select(AuditLog))
        return result.scalars().all()

    @staticmethod
    async def get_audit_log_by_id(db: AsyncSession, log_id: UUID):
        return await db.get(AuditLog, log_id)

    @staticmethod
    async def create_audit_log(db: AsyncSession, payload: dict[str, Any]):
        obj = AuditLog(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    # Note: Audit logs typically shouldn't be updated or deleted for security reasons,
    # but the methods are included here to maintain architectural consistency.
    @staticmethod
    async def update_audit_log(db: AsyncSession, log_id: UUID, payload: dict[str, Any]):
        obj = await db.get(AuditLog, log_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_audit_log(db: AsyncSession, log_id: UUID) -> bool:
        obj = await db.get(AuditLog, log_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True