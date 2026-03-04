from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.categories.schema import CategoryRead # Ensure this exists
from app.modules.categories.service import CategoryService

router = APIRouter(prefix="/categories")

@router.get("/", response_model=list[CategoryRead])
async def list_categories(db: AsyncSession = Depends(get_db)):
    return await CategoryService.get_all_categories(db)

@router.get("/{item_id}", response_model=CategoryRead)
async def get_category(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await CategoryService.get_category_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return obj

@router.post("/", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    return await CategoryService.create_category(db, payload)

@router.put("/{item_id}", response_model=CategoryRead)
async def update_category(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await CategoryService.update_category(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await CategoryService.delete_category(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")