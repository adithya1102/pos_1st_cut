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
from app.modules.carevo_pos.deps import get_outlet_manager
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


# ------------- Owner self-serve payment settings (migration 035) ------------
@router.get("/outlet/payment-methods", response_model=s.OwnerPaymentMethodsOut)
async def get_outlet_payment_methods(
    staff: User = Depends(get_outlet_manager),
    db: AsyncSession = Depends(get_db),
):
    """What this outlet accepts, and what it is permitted to accept.

    OWNER / MANAGER only — see carevo_pos/deps.py for the role model and for
    why a role-less account (which is what register_owner produces, and so what
    every real owner has) is allowed while a waiter or kitchen account is not.

    Returns cashfree_unlocked so the app can draw the Cashfree toggle as locked
    with a reason rather than as a switch that flips back.
    """
    return await CarevoService.get_owner_payment_methods(
        db, _require_outlet(staff))


@router.patch("/outlet/payment-methods", response_model=s.OwnerPaymentMethodsOut)
async def set_outlet_payment_methods(
    payload: s.OwnerPaymentMethodsIn,
    staff: User = Depends(get_outlet_manager),
    db: AsyncSession = Depends(get_db),
):
    """The owner changes how their restaurant takes money.

    Scoped to the caller's own outlet via _require_outlet — there is no
    outlet_id parameter — so one restaurant cannot reconfigure another's.

    Four rules, each a refusal with a readable message rather than a silent
    correction (see set_owner_payment_methods):

      * at least one method must be on                       -> 422
      * prepaid needs the platform unlock                    -> 409
      * UPI needs a VPA, a payee name and an attestation      -> 422
      * changing the VPA voids the attestation and turns UPI off until it is
        re-attested — because the old proof was about the old string, and a
        one-character typo inheriting it would send a customer's money to a
        stranger with CareVo not in the path to recover it.
    """
    return await CarevoService.set_owner_payment_methods(
        db, _require_outlet(staff), payload, actor_user_id=staff.id)


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
        # 034: "could not reach them" is a different no from "we won't make
        # this", and the server records the difference on call_state and in its
        # own event. Inert for a prepaid order.
        unreachable=bool(payload.unreachable) if payload else False,
        # 035: for a CLAIMED direct-UPI order, which kind of no this is —
        # 'not_received' (the customer's strike, nothing owed) or
        # 'cannot_make' (the restaurant owes the money back directly). Inert
        # for every other mode and for an unclaimed order.
        upi_outcome=(payload.upi_outcome if payload else None),
    )


# ---------------------- Pay at pickup (migration 034) ------------------------
@router.post("/orders/{order_id}/call", response_model=s.CallPlacedOut)
async def log_call(
    order_id: uuid.UUID,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Record that staff rang the customer about a pay-at-pickup order.

    PAY-AT-PICKUP ONLY: a prepaid order 404s, for the same reason a
    cross-outlet id does — "exists but is not that kind" is information about
    orders the caller has no business enumerating.

    Does NOT decide the order and does NOT extend the deadline. The call is
    evidence somebody is working it, not a decision, and letting it push the
    window out would make "ring and do nothing" a way to park an order while
    the customer waits — the trap /alert-ack was already designed to avoid.

    Counts up rather than refusing a second call: ringing twice because nobody
    answered the first time is normal. first_call_at keeps the first attempt.
    """
    return await CarevoService.log_call(
        db, order_id, _require_outlet(staff), actor_user_id=staff.id)


@router.post("/orders/{order_id}/collect", response_model=s.CollectOrderOut)
async def collect_order(
    order_id: uuid.UUID,
    payload: s.CollectOrderIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Take the money and hand the food over, in ONE transaction.

    This is the pay-at-pickup counterpart to /orders/verify-pickup, and it is a
    separate endpoint rather than a flag on that one because the two halves are
    inseparable: recording payment without closing the order leaves money
    against food still on the counter, and closing without recording payment
    gives it away. One transaction is the only shape with neither failure.

    CODE-GATED exactly like the prepaid handover. A wrong code costs an attempt
    and locks the order at three, and neither the payment nor the completion
    happens — it answers 200 with collected=false rather than a 4xx, so the app
    can tell "wrong code" from "the request failed".

    Compare-and-set on status, so two tablets tapping Collect resolve to one
    winner and the loser is told what beat it.
    """
    return await CarevoService.collect_order(
        db, order_id, _require_outlet(staff),
        pickup_code=payload.pickup_code, method=payload.method,
        actor_user_id=staff.id)


@router.post("/orders/{order_id}/payment-not-received",
             response_model=s.PaymentNotReceivedOut)
async def report_payment_not_received(
    order_id: uuid.UUID,
    staff: User = Depends(get_outlet_manager),
    db: AsyncSession = Depends(get_db),
):
    """An expired direct-UPI claim's money never arrived (migration 035).

    THE GAP THIS CLOSES. When a claim expires unanswered the order is
    cancelled with manual_refund_due = true, deliberately: nobody looked, so an
    honest customer whose money really left their account must not be stranded.
    The cost is that a restaurant holding no payment is also holding a refund
    obligation, with no way to say so. This is that way.

    OWNER / MANAGER only — the same gate as the payment settings, because the
    side effect is a penalty on a customer's account and a reversal of a
    refund. Outlet-scoped via _require_outlet; a cross-outlet id is a 404.

    Allowed ONLY on a CANCELLED direct-UPI order whose reason is
    acceptance_expired_after_payment_claim, and only within 7 days. A
    cannot_make cancellation is refused: there the restaurant said the money
    WAS there, and letting one tap undo that would both cancel a refund it owes
    and strike the customer for its own change of mind.

    Idempotent, by compare-and-set on the reason — so a double-tap records one
    strike, not two.
    """
    return await CarevoService.report_payment_not_received(
        db, order_id, _require_outlet(staff), actor_user_id=staff.id)


@router.post("/orders/{order_id}/no-show", response_model=s.NoShowOut)
async def mark_no_show(
    order_id: uuid.UUID,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """The customer never came for a pay-at-pickup order.

    -> ABANDONED, a strike on the customer, and NO refund flagged: nothing was
    ever charged. It is the one terminal cause that costs the restaurant real
    food, which is why it is the one that increments no_show_count.

    Allowed from PREPARING or READY only. An order nobody has confirmed yet is
    not a no-show — it is an unanswered order, and the call window owns that.
    """
    return await CarevoService.mark_no_show(
        db, order_id, _require_outlet(staff), actor_user_id=staff.id)


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
