from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.users.schema import UserRead, UserCreate
from app.modules.users.service import UserService
from app.modules.carevo_customer.deps import get_current_staff


# STAFF-ONLY, ROUTER-WIDE.
#
# Every route in this file was reachable with no credentials at all. A caller
# audit across GustoPOS, GustoWaiter, admin_app, owner_app, customer_app,
# gusto_pos/customer_app, dashboard_app and mcp_server found NOTHING calling
# /users — which is what makes closing it router-wide safe here, where the
# same change on orders/ or menus/ would take the tills offline.
#
# Applied on the ROUTER rather than per route, matching customers/ and
# outlets/: a per-route list is a list someone can forget to extend, and the
# next endpoint added to this file would be born unauthenticated.
#
# Exposed before this change: the whole staff-user table, plus unauthenticated user CREATION with arbitrary role_ids and unauthenticated DELETE.
router = APIRouter(prefix="/users", dependencies=[Depends(get_current_staff)])

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