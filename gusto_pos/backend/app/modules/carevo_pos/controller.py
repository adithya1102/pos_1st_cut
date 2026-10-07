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

router = APIRouter(prefix="/pos", tags=["Gusto Skip — POS"])


def _require_outlet(staff: User) -> uuid.UUID:
    if not staff.outlet_id:
        raise HTTPException(status_code=403, detail="Staff account is not assigned to an outlet")
    return staff.outlet_id


@router.post("/orders/lookup-pickup", response_model=s.LookupPickupOut)
async def lookup_pickup(
    payload: s.LookupPickupIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Find a live order at the caller's own outlet by its pickup code.

    Read-only: it shows staff what to hand over. Closing the order is a
    separate, explicit call to /orders/verify-pickup.

    There is no outlet_id parameter — the outlet comes from the caller's own
    account, so a code belonging to another outlet cannot be looked up here.

    Consecutive misses are capped per outlet (PICKUP_MISS_LIMIT over
    PICKUP_MISS_WINDOW_SECONDS) and answered with 429 + Retry-After. A found
    code clears the run.
    """
    return await CarevoService.lookup_pickup(
        db, _require_outlet(staff), payload.pickup_code
    )


@router.post("/orders/verify-pickup", response_model=s.VerifyPickupOut)
async def verify_pickup(
    payload: s.VerifyPickupIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Confirm the code and close the order.

    Scoped to the caller's own outlet. It previously was not: the staff
    dependency was bound but never used, so the order_id in the body was
    resolved unscoped and any authenticated staff account could complete any
    outlet's order.

    An order_id that resolves to nothing at this outlet is a 404 AND counts
    toward the same per-outlet miss cap as lookup-pickup (429 + Retry-After).
    The per-order 3-strike lockout is unchanged and still owns the case where
    the order IS found and the code is wrong.
    """
    return await CarevoService.verify_pickup(
        db, payload.order_id, payload.pickup_code, _require_outlet(staff)
    )


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


@router.patch("/outlet/hours", response_model=s.OwnerOutletOut)
async def set_outlet_hours(
    payload: s.SetHoursIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Set/clear the daily opening & closing schedule (migration 024).

    Scoped to the caller's own outlet via _require_outlet — no outlet_id
    parameter — so one owner cannot set another's hours.
    """
    return await CarevoService.set_outlet_hours(
        db, _require_outlet(staff), payload.opening_time, payload.closing_time
    )


@router.patch("/outlet/location", response_model=s.OwnerOutletOut)
async def set_outlet_location(
    payload: s.SetOutletLocationIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Pin the outlet's coordinates from the owner's own device.

    Scoped to the caller's own outlet via _require_outlet — there is no
    outlet_id parameter — so one owner cannot move another's pin onto their
    own street and hijack the customer app's distance sort.
    """
    return await CarevoService.set_outlet_location(
        db, _require_outlet(staff), payload.latitude, payload.longitude
    )


@router.post("/outlet/closed", response_model=s.OwnerOutletOut)
async def set_outlet_manual_closed(
    payload: s.SetManualClosedIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Flip the on-demand 'temporarily closed' toggle (migration 024).
    Independent of scheduled hours and of storefront visibility."""
    return await CarevoService.set_outlet_manual_closed(
        db, _require_outlet(staff), payload.is_manually_closed
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


@router.post("/orders/{order_id}/accept", response_model=s.AcceptOrderOut)
async def accept_order(
    order_id: uuid.UUID,
    payload: s.AcceptOrderIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Accept a pending order (manual-acceptance outlets only, migration 032).

    Exists ONLY for `outlets.acceptance_mode='manual'`. At an auto outlet no
    order is ever in AWAITING, so every call here 409s — which is the honest
    answer: there is nothing to accept, the order was accepted on payment.

    Compare-and-set on acceptance_state='AWAITING', so of two devices tapping
    Accept, or an Accept arriving as the deadline sweeper expires the order,
    exactly one wins and the loser gets 409 with the state that beat it.
    Outlet-scoped: another outlet's order id is 404, not 403.

    The events written are DELIBERATELY the same pair auto mode writes —
    ORDER_ACCEPTED then PREP_STARTED — so nothing in prediction/ needs to
    change. Only `source` ('tap' instead of 'inferred'), the staff actor and
    the prep_minutes payload differ, all of which are fields that stream
    already carries. The single genuinely new datum is accepted_at.
    """
    from app.modules.carevo_customer.acceptance import AcceptanceService

    return await AcceptanceService.accept(
        db, order_id, _require_outlet(staff),
        prep_minutes=payload.prep_minutes, actor_user_id=staff.id,
    )


@router.post("/orders/{order_id}/alert-ack", response_model=s.AlertAckOut)
async def acknowledge_alert(
    order_id: uuid.UUID,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """"I have seen this alert" — stops the re-push ladder for one order.

    Does NOT accept the order and does NOT stop the deadline. A restaurant that
    has seen the alert and then done nothing must still expire, otherwise
    acknowledging would become a way to park orders indefinitely while the
    customer waits.

    Answers 200 with acknowledged=false when the order is no longer AWAITING,
    rather than 409: an ack racing the accept/reject/expiry it describes is the
    normal case on a tablet with several devices, not a client error.
    """
    from app.modules.carevo_customer.acceptance import AcceptanceService

    return await AcceptanceService.acknowledge(
        db, order_id, _require_outlet(staff))


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


@router.post("/devices/test-push", response_model=s.TestPushOut)
async def send_test_push(
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Send a real push to the CALLER'S OWN device. Rate-limited 3/min.

    Exists because "are alerts working on this tablet?" is otherwise only
    answerable by waiting for a real order, and the answer matters most on the
    devices that have never received one. It is the button behind owner_app's
    Settings -> Send test alert.

    Aimed at the caller's own users.fcm_token and nothing else — there is no
    parameter that could point it at another device, so it cannot be used to
    buzz a colleague.

    Returns the TRANSPORT RESULT rather than a bare ok. 'skipped' with a reason
    is the common and useful case: it distinguishes "this device never
    registered a token" from "push is disabled on this deployment" from "FCM
    rejected it", and those have three different fixes. A staff member reading
    "no fcm_token" knows to grant notification permission; "push disabled"
    is an operator problem they should stop investigating.
    """
    from app.modules.push.service import PushService, KIND_NEW_ORDER_PENDING

    CarevoService.check_test_push_rate_limit(staff.id)

    res = await PushService.send_staff(
        db, user_id=staff.id, kind=KIND_NEW_ORDER_PENDING,
        title="Test alert",
        body="If you can see and hear this, order alerts are working.",
        data={"test": "true", "attempt": "1"},
    )
    await db.commit()
    return {"status": res["status"], "detail": res.get("detail")}


@router.post("/menu-items/{item_id}/stock", response_model=s.SetStockOut)
async def set_item_stock(
    item_id: uuid.UUID,
    payload: s.SetStockIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear an item's limited quantity for today (migration 033).

    `quantity: null` means UNTRACKED — unlimited, which is how every item
    behaves today and the escape hatch for a restaurant that turned counting on
    and regretted it. A number starts tracking it.

    Outlet-scoped through the menu_items -> categories -> menus -> outlet chain,
    so one restaurant cannot set another's stock.

    Setting a positive number on a sold-out item also flips is_available back
    on, because "there are 5 again" and "it is orderable" are one statement
    from the owner's point of view; making them two taps is how a dish ends up
    hidden with stock sitting behind it.
    """
    from app.modules.carevo_customer.stock import StockService

    return await StockService.set_stock(
        db, item_id, _require_outlet(staff), payload.quantity)
