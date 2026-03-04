from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.roles.model import Role

class RoleService:
    @staticmethod
    async def get_all_roles(db: AsyncSession):
        result = await db.execute(select(Role))
        return result.scalars().all()

    @staticmethod
    async def get_role_by_id(db: AsyncSession, role_id: int):
        return await db.get(Role, role_id)

    @staticmethod
    async def create_role(db: AsyncSession, payload: dict[str, Any]):
        obj = Role(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def update_role(db: AsyncSession, role_id: int, payload: dict[str, Any]):
        obj = await db.get(Role, role_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_role(db: AsyncSession, role_id: int) -> bool:
        obj = await db.get(Role, role_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True