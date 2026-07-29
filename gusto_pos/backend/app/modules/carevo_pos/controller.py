"""CareVo Skip POS routes (staff-authenticated). Mounted under /api/v1.

Includes the Owner App endpoints (outlet visibility, per-dish availability,
active order feed, and customer notify). Every route is staff-authed via
get_current_staff and scoped to the caller's own outlet (user.outlet_id).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_customer import schema as s
from app.modules.carevo_customer.deps import get_current_staff
from app.modules.carevo_customer.service import CarevoService
from app.modules.users.model import User

router = APIRouter(prefix="/pos", tags=["CareVo Skip — POS"])


def _require_outlet(staff: User) -> uuid.UUID:
    if not staff.outlet_id:
        raise HTTPException(status_code=403, detail="Staff account is not assigned to an outlet")
    return staff.outlet_id


@router.post("/orders/verify-pickup", response_model=s.VerifyPickupOut)
async def verify_pickup(
    payload: s.VerifyPickupIn,
    _staff=Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.verify_pickup(db, payload.order_id, payload.pickup_code)


# ------------------------------ Owner App ----------------------------------
@router.get("/outlet", response_model=s.OwnerOutletOut)
async def get_outlet(
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.get_owner_outlet(db, _require_outlet(staff))


@router.post("/outlets/{outlet_id}/visibility", response_model=s.SetVisibilityOut)
async def set_visibility(
    outlet_id: uuid.UUID,
    payload: s.SetVisibilityIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    if str(outlet_id) != str(_require_outlet(staff)):
        raise HTTPException(status_code=403, detail="Cannot modify another outlet")
    return await CarevoService.set_outlet_visibility(db, outlet_id, payload.is_visible)


@router.get("/menu-items", response_model=list[s.OwnerMenuItemOut])
async def list_menu_items(
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.list_owner_menu_items(db, _require_outlet(staff))


@router.patch("/menu-items/{item_id}/availability", response_model=s.SetAvailabilityOut)
async def set_item_availability(
    item_id: uuid.UUID,
    payload: s.SetAvailabilityIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.set_item_availability(
        db, item_id, _require_outlet(staff), payload.is_available
    )


# ------------------------- Menu CRUD (Owner App) ---------------------------
@router.get("/categories", response_model=list[s.OwnerCategoryOut])
async def list_categories(
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.list_owner_categories(db, _require_outlet(staff))


@router.post("/menu-items", response_model=s.OwnerMenuItemOut, status_code=201)
async def create_menu_item(
    payload: s.CreateMenuItemIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.create_menu_item(db, _require_outlet(staff), payload)


@router.patch("/menu-items/{item_id}", response_model=s.OwnerMenuItemOut)
async def update_menu_item(
    item_id: uuid.UUID,
    payload: s.UpdateMenuItemIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.update_menu_item(db, item_id, _require_outlet(staff), payload)


@router.delete("/menu-items/{item_id}", response_model=s.DeleteMenuItemOut)
async def delete_menu_item(
    item_id: uuid.UUID,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.delete_menu_item(db, item_id, _require_outlet(staff))


@router.get("/orders", response_model=list[s.OwnerOrderOut])
async def list_active_orders(
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.list_active_orders(db, _require_outlet(staff))


@router.post("/orders/{order_id}/mark-paid", response_model=s.MarkPaidOut)
async def mark_order_paid(
    order_id: uuid.UUID,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Manual payment confirmation for the UPI-intent flow."""
    return await CarevoService.mark_order_paid_by_staff(db, order_id, _require_outlet(staff))


@router.post("/orders/{order_id}/notify", response_model=s.NotifyOut)
async def notify_order(
    order_id: uuid.UUID,
    payload: s.NotifyIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.notify_order(
        db, order_id, _require_outlet(staff), payload.type, payload.item_id
    )
