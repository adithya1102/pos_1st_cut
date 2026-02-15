from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.outlets.schema import OutletRead
from app.modules.outlets.model import Outlet
from app.core.dependencies import get_db_dep

# FIXED: Removed prefix and tags
router = APIRouter()

@router.get("/", response_model=list[OutletRead])
async def list_outlets(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(Outlet))
    return result.scalars().all()

@router.get("/{item_id}", response_model=OutletRead)
async def get_outlet(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Outlet, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet not found")
    return obj

@router.post("/", response_model=OutletRead, status_code=status.HTTP_201_CREATED)
async def create_outlet(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = Outlet(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.put("/{item_id}", response_model=OutletRead)
async def update_outlet(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(Outlet, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outlet(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Outlet, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet not found")
    await db.delete(obj)
    await db.commit()