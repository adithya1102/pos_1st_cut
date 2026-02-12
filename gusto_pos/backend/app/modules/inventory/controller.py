from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.schema import InventoryRead
from app.modules.inventory.model import Inventory
from app.core.dependencies import get_db_dep

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/", response_model=list[InventoryRead])
async def list_inventory(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(Inventory))
    return result.scalars().all()


@router.get("/{item_id}", response_model=InventoryRead)
async def get_inventory(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Inventory, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory not found")
    return obj


@router.post("/", response_model=InventoryRead, status_code=status.HTTP_201_CREATED)
async def create_inventory(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = Inventory(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{item_id}", response_model=InventoryRead)
async def update_inventory(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(Inventory, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inventory(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Inventory, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory not found")
    await db.delete(obj)
    await db.commit()
