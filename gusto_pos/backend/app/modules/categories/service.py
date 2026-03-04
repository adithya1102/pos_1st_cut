from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.menu.model import MenuCategory as Category

class CategoryService:
    @staticmethod
    async def get_all_categories(db: AsyncSession):
        result = await db.execute(select(Category))
        return result.scalars().all()

    @staticmethod
    async def get_category_by_id(db: AsyncSession, category_id: UUID):
        return await db.get(Category, category_id)

    @staticmethod
    async def create_category(db: AsyncSession, payload: dict[str, Any]):
        obj = Category(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def update_category(db: AsyncSession, category_id: UUID, payload: dict[str, Any]):
        obj = await db.get(Category, category_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_category(db: AsyncSession, category_id: UUID) -> bool:
        obj = await db.get(Category, category_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True