from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.payments.schema import PaymentRead
from app.modules.payments.service import PaymentService

router = APIRouter(prefix="/payments")

@router.get("/", response_model=list[PaymentRead])
async def list_payments(db: AsyncSession = Depends(get_db)):
    return await PaymentService.get_all_payments(db)

@router.get("/{item_id}", response_model=PaymentRead)
async def get_payment(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await PaymentService.get_payment_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return obj

@router.post("/", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def create_payment(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    return await PaymentService.create_payment(db, payload)

@router.put("/{item_id}", response_model=PaymentRead)
async def update_payment(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await PaymentService.update_payment(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await PaymentService.delete_payment(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")