from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.users.model import User
from app.modules.users.schema import UserCreate
from app.core.security import get_password_hash

class UserService:
    @staticmethod
    async def get_all_users(db: AsyncSession):
        result = await db.execute(select(User))
        return result.scalars().all()

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: UUID):
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user(db: AsyncSession, payload: UserCreate):
        hashed = get_password_hash(payload.password)
        obj = User(
            username=payload.username,
            hashed_password=hashed,
            is_active=payload.is_active,
            role_id=payload.role_id,
            outlet_id=payload.outlet_id
        )
        db.add(obj)
        await db.commit()
        result = await db.execute(
            select(User).where(User.id == obj.id)
        )
        return result.scalar_one()

    @staticmethod
    async def update_user(db: AsyncSession, user_id: UUID, payload: dict[str, Any]):
        obj = await db.get(User, user_id)
        if not obj:
            return None
        for k, v in payload.items():
            # If they are updating the password, hash it first
            if k == "password":
                v = get_password_hash(v)
                k = "hashed_password"
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one()

    @staticmethod
    async def delete_user(db: AsyncSession, user_id: UUID) -> bool:
        obj = await db.get(User, user_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True