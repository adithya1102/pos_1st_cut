from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.schema import UserRead, UserCreate
from app.modules.users.model import User
from app.core.dependencies import get_db_dep
from app.core.security import get_password_hash, verify_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=list[UserRead])
async def list_users(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(User))
    return result.scalars().all()


@router.get("/{item_id}", response_model=UserRead)
async def get_user(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(User, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return obj


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate = Body(...), db: AsyncSession = get_db_dep()):
    hashed = get_password_hash(payload.password)
    obj = User(username=payload.username, hashed_password=hashed, is_active=payload.is_active, role_id=payload.role_id, outlet_id=payload.outlet_id)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{item_id}", response_model=UserRead)
async def update_user(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(User, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(User, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await db.delete(obj)
    await db.commit()
