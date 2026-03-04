from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.payments.model import Payment

class PaymentService:
    @staticmethod
    async def get_all_payments(db: AsyncSession):
        result = await db.execute(select(Payment))
        return result.scalars().all()

    @staticmethod
    async def get_payment_by_id(db: AsyncSession, payment_id: UUID):
        return await db.get(Payment, payment_id)

    @staticmethod
    async def create_payment(db: AsyncSession, payload: dict[str, Any]):
        obj = Payment(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def update_payment(db: AsyncSession, payment_id: UUID, payload: dict[str, Any]):
        obj = await db.get(Payment, payment_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_payment(db: AsyncSession, payment_id: UUID) -> bool:
        obj = await db.get(Payment, payment_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True