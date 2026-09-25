from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.inventory.schema import InventoryRead
from app.modules.inventory.service import InventoryService
from app.modules.carevo_customer.deps import get_current_staff


# STAFF-ONLY, ROUTER-WIDE.
#
# Every route in this file was reachable with no credentials at all. A caller
# audit across GustoPOS, GustoWaiter, admin_app, owner_app, customer_app,
# gusto_pos/customer_app, dashboard_app and mcp_server found NOTHING calling
# /inventory — which is what makes closing it router-wide safe here, where the
# same change on orders/ or menus/ would take the tills offline.
#
# Applied on the ROUTER rather than per route, matching customers/ and
# outlets/: a per-route list is a list someone can forget to extend, and the
# next endpoint added to this file would be born unauthenticated.
#
# Exposed before this change: stock CRUD.
router = APIRouter(prefix="/inventory", dependencies=[Depends(get_current_staff)])

@router.get("/", response_model=list[InventoryRead])
async def list_inventory(db: AsyncSession = Depends(get_db)):
    return await InventoryService.get_all_inventory(db)

@router.get("/{item_id}", response_model=InventoryRead)
async def get_inventory(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await InventoryService.get_inventory_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    return obj

@router.post("/", response_model=InventoryRead, status_code=status.HTTP_201_CREATED)
async def create_inventory(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    return await InventoryService.create_inventory(db, payload)

@router.put("/{item_id}", response_model=InventoryRead)
async def update_inventory(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await InventoryService.update_inventory(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inventory(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await InventoryService.delete_inventory(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")