from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.payments.model import Payment

# Only keep known DB columns when constructing a Payment
_PAYMENT_COLUMNS = {"order_id", "amount", "payment_method"}


class PaymentService:
    @staticmethod
    async def get_all_payments(db: AsyncSession):
        result = await db.execute(select(Payment))
        return result.scalars().all()

    @staticmethod
    async def get_payment_by_id(db: AsyncSession, payment_id: UUID):
        result = await db.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_payment(db: AsyncSession, payload: dict[str, Any]):
        filtered = {k: v for k, v in payload.items() if k in _PAYMENT_COLUMNS}
        obj = Payment(**filtered)
        db.add(obj)
        await db.commit()
        result = await db.execute(
            select(Payment).where(Payment.id == obj.id)
        )
        return result.scalar_one()

    @staticmethod
    async def update_payment(db: AsyncSession, payment_id: UUID, payload: dict[str, Any]):
        obj = await db.get(Payment, payment_id)
        if not obj:
            return None
        for k, v in payload.items():
            if k in _PAYMENT_COLUMNS:
                setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        result = await db.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one()

    @staticmethod
    async def delete_payment(db: AsyncSession, payment_id: UUID) -> bool:
        obj = await db.get(Payment, payment_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True