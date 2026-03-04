from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.order_items.model import OrderItem

class OrderItemService:
    @staticmethod
    async def get_all_order_items(db: AsyncSession):
        result = await db.execute(select(OrderItem))
        return result.scalars().all()

    @staticmethod
    async def get_order_item_by_id(db: AsyncSession, item_id: UUID):
        return await db.get(OrderItem, item_id)

    @staticmethod
    async def create_order_item(db: AsyncSession, payload: dict[str, Any]):
        obj = OrderItem(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def update_order_item(db: AsyncSession, item_id: UUID, payload: dict[str, Any]):
        obj = await db.get(OrderItem, item_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_order_item(db: AsyncSession, item_id: UUID) -> bool:
        obj = await db.get(OrderItem, item_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True