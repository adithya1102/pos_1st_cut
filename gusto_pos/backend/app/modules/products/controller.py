from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.schema import ProductRead
from app.modules.products.model import Product
from app.core.dependencies import get_db_dep

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/", response_model=list[ProductRead])
async def list_products(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(Product))
    return result.scalars().all()


@router.get("/{item_id}", response_model=ProductRead)
async def get_product(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Product, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return obj


@router.post("/", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = Product(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{item_id}", response_model=ProductRead)
async def update_product(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(Product, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(Product, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    await db.delete(obj)
    await db.commit()
