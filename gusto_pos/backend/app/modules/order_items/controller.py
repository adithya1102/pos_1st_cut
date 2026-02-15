from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.order_items.schema import OrderItemRead
from app.modules.order_items.model import OrderItem
from app.core.dependencies import get_db_dep

# Router prefix and tags moved to main.py
router = APIRouter()


@router.get("/", response_model=list[OrderItemRead])
async def list_order_items(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(OrderItem))
    return result.scalars().all()


@router.get("/{item_id}", response_model=OrderItemRead)
async def get_order_item(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(OrderItem, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order item not found")
    return obj


@router.post("/", response_model=OrderItemRead, status_code=status.HTTP_201_CREATED)
async def create_order_item(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = OrderItem(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{item_id}", response_model=OrderItemRead)
async def update_order_item(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(OrderItem, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order item not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order_item(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(OrderItem, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order item not found")
    await db.delete(obj)
    await db.commit()
