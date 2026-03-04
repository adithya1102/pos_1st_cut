from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.orders.model import Order

class OrderService:
    @staticmethod
    async def get_all_orders(db: AsyncSession):
        result = await db.execute(select(Order))
        return result.scalars().all()

    @staticmethod
    async def get_order_by_id(db: AsyncSession, order_id: UUID):
        return await db.get(Order, order_id)

    @staticmethod
    async def create_order(db: AsyncSession, payload: dict[str, Any]):
        obj = Order(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def update_order(db: AsyncSession, order_id: UUID, payload: dict[str, Any]):
        obj = await db.get(Order, order_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_order(db: AsyncSession, order_id: UUID) -> bool:
        obj = await db.get(Order, order_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True