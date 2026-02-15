from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.schema import CategoryRead
from app.modules.categories.model import Category
from app.core.dependencies import get_db_dep

# Router prefix and tags moved to main.py
router = APIRouter()


@router.get("/", response_model=list[CategoryRead])
async def list_categories(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(Category))
    return result.scalars().all()


@router.get("/{item_id}", response_model=CategoryRead)
async def get_category(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Category, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return obj


@router.post("/", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = Category(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{item_id}", response_model=CategoryRead)
async def update_category(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(Category, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Category, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    await db.delete(obj)
    await db.commit()
