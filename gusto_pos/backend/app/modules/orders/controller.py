from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.schema import OrderRead
from app.modules.orders.model import Order
from app.core.dependencies import get_db_dep

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/", response_model=list[OrderRead])
async def list_orders(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(Order))
    return result.scalars().all()


@router.get("/{item_id}", response_model=OrderRead)
async def get_order(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Order, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return obj


@router.post("/", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = Order(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{item_id}", response_model=OrderRead)
async def update_order(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(Order, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Order, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    await db.delete(obj)
    await db.commit()
