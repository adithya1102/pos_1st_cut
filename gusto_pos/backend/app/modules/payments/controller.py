from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.schema import PaymentRead
from app.modules.payments.model import Payment
from app.core.dependencies import get_db_dep

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/", response_model=list[PaymentRead])
async def list_payments(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(Payment))
    return result.scalars().all()


@router.get("/{item_id}", response_model=PaymentRead)
async def get_payment(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Payment, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return obj


@router.post("/", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def create_payment(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = Payment(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{item_id}", response_model=PaymentRead)
async def update_payment(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(Payment, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Payment, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    await db.delete(obj)
    await db.commit()
