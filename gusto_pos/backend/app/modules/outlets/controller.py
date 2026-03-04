from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.outlets.schema import OutletRead, OutletCreate, OutletUpdate
from app.modules.outlets.service import OutletService

router = APIRouter(prefix="/outlets")

@router.get("/", response_model=list[OutletRead])
async def list_outlets(db: AsyncSession = Depends(get_db)):
    return await OutletService.get_all_outlets(db)

@router.get("/{item_id}", response_model=OutletRead)
async def get_outlet(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await OutletService.get_outlet_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet not found")
    return obj

@router.post("/", response_model=None, status_code=status.HTTP_201_CREATED)
async def create_outlet(payload: OutletCreate, db: AsyncSession = Depends(get_db)):
    return await OutletService.create_outlet(db, payload.model_dump())

@router.put("/{item_id}", response_model=OutletRead)
async def update_outlet(item_id: UUID, payload: OutletUpdate, db: AsyncSession = Depends(get_db)):
    obj = await OutletService.update_outlet(db, item_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outlet(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await OutletService.delete_outlet(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet not found")