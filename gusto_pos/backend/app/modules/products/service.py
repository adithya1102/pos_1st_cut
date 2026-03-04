from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.products.model import Product

class ProductService:
    @staticmethod
    async def get_all_products(db: AsyncSession):
        result = await db.execute(select(Product))
        return result.scalars().all()

    @staticmethod
    async def get_product_by_id(db: AsyncSession, product_id: UUID):
        return await db.get(Product, product_id)

    @staticmethod
    async def create_product(db: AsyncSession, payload: dict[str, Any]):
        obj = Product(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def update_product(db: AsyncSession, product_id: UUID, payload: dict[str, Any]):
        obj = await db.get(Product, product_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_product(db: AsyncSession, product_id: UUID) -> bool:
        obj = await db.get(Product, product_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True