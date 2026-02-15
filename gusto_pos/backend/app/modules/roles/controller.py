from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.roles.schema import RoleRead
from app.modules.roles.model import Role
from app.core.dependencies import get_db_dep

# FIXED: Removed prefix and tags
router = APIRouter()

@router.get("/", response_model=list[RoleRead])
async def list_roles(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(Role))
    return result.scalars().all()

@router.get("/{item_id}", response_model=RoleRead)
async def get_role(item_id: int, db: AsyncSession = get_db_dep()):
    obj = await db.get(Role, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return obj

@router.post("/", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = Role(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.put("/{item_id}", response_model=RoleRead)
async def update_role(item_id: int, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(Role, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(item_id: int, db: AsyncSession = get_db_dep()):
    obj = await db.get(Role, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    await db.delete(obj)
    await db.commit()