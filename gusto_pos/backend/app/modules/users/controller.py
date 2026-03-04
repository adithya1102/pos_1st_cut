from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.users.schema import UserRead, UserCreate
from app.modules.users.service import UserService

router = APIRouter(prefix="/users")

@router.get("/", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_db)):
    return await UserService.get_all_users(db)

@router.get("/{item_id}", response_model=UserRead)
async def get_user(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await UserService.get_user_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return obj

@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate = Body(...), db: AsyncSession = Depends(get_db)):
    return await UserService.create_user(db, payload)

@router.put("/{item_id}", response_model=UserRead)
async def update_user(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await UserService.update_user(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await UserService.delete_user(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")