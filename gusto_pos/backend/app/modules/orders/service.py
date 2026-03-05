from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.orders.model import Order
from app.modules.orders.schema import OrderCreate, OrderUpdate

class OrderService:
    @staticmethod
    async def get_all_orders(db: AsyncSession):
        result = await db.execute(select(Order))
        return result.scalars().all()

    @staticmethod
    async def get_order_by_id(db: AsyncSession, order_id: UUID):
        result = await db.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_order(db: AsyncSession, payload: OrderCreate):
        obj = Order(
            outlet_id=payload.outlet_id,
            table_id=payload.table_id,
            customer_id=payload.customer_id,
            total_amount=payload.total_amount,
            order_status=payload.order_status.value if payload.order_status else "pending",
            kitchen_token=payload.kitchen_token,
        )
        db.add(obj)
        await db.commit()
        # Re-fetch instead of db.refresh to avoid MissingGreenlet / cascade
        result = await db.execute(select(Order).where(Order.id == obj.id))
        return result.scalar_one()

    @staticmethod
    async def update_order(db: AsyncSession, order_id: UUID, payload: OrderUpdate):
        obj = await OrderService.get_order_by_id(db, order_id)
        if not obj:
            return None
        for k, v in payload.model_dump(exclude_unset=True).items():
            if k == "order_status" and v is not None:
                v = v.value if hasattr(v, "value") else v
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        result = await db.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one()

    @staticmethod
    async def delete_order(db: AsyncSession, order_id: UUID) -> bool:
        obj = await OrderService.get_order_by_id(db, order_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True