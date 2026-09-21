from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.outlets.schema import OutletRead, OutletCreate, OutletUpdate
from app.modules.outlets.service import OutletService
from app.modules.carevo_customer.deps import get_current_staff

# STAFF-ONLY, ROUTER-WIDE. This whole file was reachable with no credentials,
# `DELETE /outlets/{id}` included, and `OutletRead` hands back `phone_number`
# and `organization_id` alongside the coordinates. Nothing in this repository
# calls it: the admin app uses `/api/v1/admin/outlets/*` and the customer app
# uses `/api/v1/customer/outlets`, both of which are separate, already-guarded
# routers and are NOT affected by this change.
#
# Router-level for the same reason as the customers module: the guard should be
# what a new route in this file inherits by default.
router = APIRouter(prefix="/outlets", dependencies=[Depends(get_current_staff)])

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