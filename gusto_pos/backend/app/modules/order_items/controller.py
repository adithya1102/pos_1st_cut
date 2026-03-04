from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.order_items.schema import OrderItemRead
from app.modules.order_items.service import OrderItemService

router = APIRouter(prefix="/order-items")

@router.get("/", response_model=list[OrderItemRead])
async def list_order_items(db: AsyncSession = Depends(get_db)):
    return await OrderItemService.get_all_order_items(db)

@router.get("/{item_id}", response_model=OrderItemRead)
async def get_order_item(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await OrderItemService.get_order_item_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order item not found")
    return obj

@router.post("/", response_model=OrderItemRead, status_code=status.HTTP_201_CREATED)
async def create_order_item(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    return await OrderItemService.create_order_item(db, payload)

@router.put("/{item_id}", response_model=OrderItemRead)
async def update_order_item(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await OrderItemService.update_order_item(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order item not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order_item(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await OrderItemService.delete_order_item(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order item not found")