from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.roles.schema import RoleRead
from app.modules.roles.service import RoleService

router = APIRouter(prefix="/roles")

@router.get("/", response_model=list[RoleRead])
async def list_roles(db: AsyncSession = Depends(get_db)):
    return await RoleService.get_all_roles(db)

@router.get("/{item_id}", response_model=RoleRead)
async def get_role(item_id: int, db: AsyncSession = Depends(get_db)):
    obj = await RoleService.get_role_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return obj

@router.post("/", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    return await RoleService.create_role(db, payload)

@router.put("/{item_id}", response_model=RoleRead)
async def update_role(item_id: int, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await RoleService.update_role(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(item_id: int, db: AsyncSession = Depends(get_db)):
    if not await RoleService.delete_role(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")