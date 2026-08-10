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


@router.patch("/outlet/image", response_model=s.OwnerOutletOut)
async def set_outlet_image(
    payload: s.SetOutletImageIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Set/clear the outlet storefront photo (migration 011).

    Scoped to the caller's own outlet via _require_outlet — there is no
    outlet_id parameter, so one owner cannot rebrand another's storefront.
    """
    return await CarevoService.set_outlet_image(
        db, _require_outlet(staff), payload.image_url
    )


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


# REMOVED: POST /orders/{id}/mark-paid.
#
# Payment confirmation is now webhook-driven end to end: the gateway tells us,
# and mark_paid fires from /customer/payment/webhook. A staff-tappable endpoint
# that flips an order to PAID is, with a real gateway behind it, a button that
# marks unpaid orders as paid — so it is gone rather than merely hidden in the
# app. CarevoService.mark_order_paid_by_staff is left in place, uncalled, for
# the UPI-intent fallback should it ever be re-enabled deliberately.


@router.post("/orders/{order_id}/reject", response_model=s.RejectOrderOut)
async def reject_order(
    order_id: uuid.UUID,
    payload: s.RejectOrderIn | None = None,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Refuse a paid order -> CANCELLED, and tell the customer.

    There is deliberately NO matching /accept: a paid order is accepted
    automatically. This is the only human gate, and it is an opt-OUT.

    Allowed up to (not including) READY — see REJECTABLE_STATUSES. Rejecting
    food that is already made and waiting is not a real-world action.
    """
    return await CarevoService.reject_order(
        db, order_id, _require_outlet(staff),
        reason=(payload.reason if payload else None),
        actor_user_id=staff.id,
    )


@router.post("/push/register", response_model=s.RegisterStaffTokenOut)
async def register_staff_push_token(
    payload: s.RegisterStaffTokenIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Store this device's FCM token against the signed-in staff user.

    Mirrors /customer/push/register. Needed because migration 014 built the
    push stack customer-only — without a token here, "notify the outlet on
    every paid order" has nowhere to send.
    """
    return await CarevoService.register_staff_push_token(db, staff.id, payload.fcm_token)


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


@router.post("/orders/{order_id}/items/unavailable",
             response_model=s.MarkItemsUnavailableOut)
async def mark_items_unavailable(
    order_id: uuid.UUID,
    payload: s.MarkItemsUnavailableIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Mark one OR MORE line items unavailable in a single staff action.

    The existing /notify?type=item_unavailable takes exactly one item_id and
    stays as-is for the single-item path. This is the batch entry point behind
    the order-detail checklist: staff tick several items and confirm once.

    One ORDER_UNAVAILABLE event and one push PER ITEM, not per batch, so each
    item stays individually attributable in the event stream and the customer
    is told which specific dish is off — "2 items unavailable" helps nobody.
    """
    return await CarevoService.mark_items_unavailable(
        db, order_id, _require_outlet(staff), payload.item_ids
    )
