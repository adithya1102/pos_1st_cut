"""CareVo Skip customer-facing routes (mounted under /api/v1)."""
from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.modules.customers.model import Customer
from app.modules.carevo_customer import schema as s
from app.modules.carevo_customer.deps import (
    create_customer_token,
    get_current_customer,
    get_current_staff,
)
from app.modules.carevo_customer.service import CarevoService

router = APIRouter(prefix="/customer", tags=["CareVo Skip — Customer"])


# ------------------------------- Auth --------------------------------------
def _require_customer_auth_enabled() -> None:
    if not settings.CUSTOMER_AUTH_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Customer login is disabled on this deployment",
        )


@router.post("/auth/request-otp", response_model=s.RequestOtpOut)
async def request_otp(payload: s.RequestOtpIn):
    _require_customer_auth_enabled()
    return CarevoService.request_otp(payload.phone_number)


@router.post("/auth/verify-otp", response_model=s.VerifyOtpOut)
async def verify_otp(payload: s.VerifyOtpIn, db: AsyncSession = Depends(get_db)):
    _require_customer_auth_enabled()
    customer = await CarevoService.verify_otp(db, payload.phone_number, payload.otp)
    token = create_customer_token(str(customer.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone_number": customer.phone_number,
        },
    }


@router.post("/auth/firebase", response_model=s.VerifyOtpOut)
async def verify_firebase(payload: s.FirebaseAuthIn, db: AsyncSession = Depends(get_db)):
    """Real phone-auth login: Firebase ID token -> CareVo customer session.

    Intentionally NOT behind _require_customer_auth_enabled(). That switch exists
    because the stub OTP path lets anyone mint a token for any phone number; this
    path proves possession of the number via Firebase, so it stays available on
    public deploys and is the intended replacement for the stub. Gated instead by
    FIREBASE_ENABLED + FIREBASE_PROJECT_ID.
    """
    customer = await CarevoService.verify_firebase_token(db, payload.id_token)
    token = create_customer_token(str(customer.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone_number": customer.phone_number,
            "email": customer.email,
        },
    }


@router.post("/auth/google", response_model=s.VerifyOtpOut)
async def verify_google(payload: s.GoogleAuthIn, db: AsyncSession = Depends(get_db)):
    """Google sign-in: Firebase Google-provider ID token -> CareVo session.

    A STANDALONE identity — the customer returned here has no phone number, and
    none is asked for. Same reasoning as /auth/firebase for skipping
    _require_customer_auth_enabled(): nothing is taken on the client's word, the
    token is verified against Google's public keys. Gated by FIREBASE_ENABLED +
    FIREBASE_PROJECT_ID.
    """
    customer = await CarevoService.verify_google_token(db, payload.id_token)
    token = create_customer_token(str(customer.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone_number": customer.phone_number,
            "email": customer.email,
        },
    }


# --------------------- Profile / loyalty / coupons (010) --------------------
# Every route here is scoped to the customer resolved from the bearer token.
# None of them accepts a customer id, so there is no path by which one customer
# can read or mutate another's profile, orders, points or coupons.
#
# Deliberately NOT gated by _require_customer_auth_enabled(): that switch guards
# the stub-OTP login path, and these all require an already-issued token.
@router.get("/me", response_model=s.MeOut)
async def get_me(
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.get_me(db, customer)


@router.patch("/me", response_model=s.MeOut)
async def update_me(
    payload: s.UpdateMeIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Name only — phone and email come from verified sign-in, not the client."""
    return await CarevoService.update_me(db, customer, payload)


@router.delete("/me", response_model=s.DeleteAccountOut)
async def delete_my_account(
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Permanently erase this account's personal data.

    Scoped to the bearer token like every other /me route — it takes no
    customer id, so nobody can delete anyone else's account.

    Play Store policy requires apps that let users create an account to offer
    an in-app deletion route. This is it. It is irreversible: there is no
    undelete, and the same phone number signing in afterwards gets a brand new,
    empty account rather than recovering this one.
    """
    return await CarevoService.delete_my_account(db, customer)


@router.get("/orders", response_model=list[s.OrderHistoryOut])
async def list_my_orders(
    limit: int = 50,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.list_my_orders(db, customer, limit=min(max(limit, 1), 200))


@router.get("/points", response_model=s.PointsOut)
async def get_points(
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.get_points(db, customer)


@router.post("/points/redeem", response_model=s.RedeemPointsOut)
async def redeem_points(
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Spend 50 points for a ₹100 single-use discount coupon. 409 if short."""
    return await CarevoService.redeem_points(db, customer)


@router.get("/coupons", response_model=list[s.CouponOut])
async def list_my_coupons(
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.list_my_coupons(db, customer)


@router.post("/coupons/redeem", response_model=s.RedeemCouponOut)
async def redeem_trial_coupon(
    payload: s.RedeemCouponIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Redeem a PREMIUM_TRIAL code — grants premium_until, no payment involved.

    POINTS_DISCOUNT coupons are NOT redeemed here; they are applied by passing
    coupon_code to POST /orders at checkout.
    """
    return await CarevoService.redeem_trial_coupon(db, customer, payload)


@router.post("/cart/check", response_model=s.CartCheckOut)
async def check_cart(
    payload: s.CartCheckIn,
    _: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Pre-checkout availability gate. Read-only; never mutates anything.

    The app calls this before taking payment so an item that went unavailable
    mid-session is surfaced while the customer can still remove it.
    POST /orders re-validates regardless — this does not replace that check.
    """
    return await CarevoService.check_cart_availability(
        db, payload.outlet_id, payload.menu_item_ids
    )


# ---------------------------- Discovery ------------------------------------
@router.get("/areas", response_model=list[s.AreaOut])
async def list_areas(
    _: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Cities that currently have at least one orderable outlet.

    Backs the location picker. Derived from live outlet rows so the app can
    never offer a location that yields an empty restaurant list.
    """
    return await CarevoService.list_areas(db)


@router.get("/outlets", response_model=list[s.OutletOut])
async def list_outlets(
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    city: Optional[list[str]] = Query(None),
    _: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Visible outlets, optionally filtered by `city` and sorted by distance.

    `city` comes from /customer/areas and is REPEATABLE:
    `?city=Bengaluru&city=Chennai` returns the union of both. It went from a
    single value to a list when the app's city picker became multi-select.

    Backwards compatible for existing callers: a single `?city=X` still parses
    into a one-element list and behaves exactly as before, and omitting it
    entirely still means "no city filter".
    """
    return await CarevoService.list_outlets(db, lat, lng, city=city)


@router.get("/menu/{outlet_id}", response_model=s.MenuOut)
async def get_menu(
    outlet_id: uuid.UUID,
    _: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.get_menu(db, outlet_id)


# ------------------------------ Orders -------------------------------------
@router.post("/orders", response_model=s.CreateOrderOut)
async def create_order(
    payload: s.CreateOrderIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.create_order(db, customer, payload)


# --------------------- PE Step 3: customer events --------------------------
@router.post("/orders/{order_id}/depart", response_model=s.EventAck)
async def depart(
    order_id: uuid.UUID,
    payload: s.DepartIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.record_departed(db, order_id, customer, payload.lat, payload.lng)


@router.post("/orders/{order_id}/location", response_model=s.EventAck)
async def location_ping(
    order_id: uuid.UUID,
    payload: s.LocationPingIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.record_location_ping(
        db, order_id, customer, payload.lat, payload.lng,
        payload.accuracy_m, payload.speed_mps)


@router.post("/orders/{order_id}/arrived", response_model=s.EventAck)
async def arrived(
    order_id: uuid.UUID,
    payload: s.ArrivedIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.record_arrived(db, order_id, customer, payload.accuracy_m, payload.source)


@router.post("/orders/{order_id}/feedback", response_model=s.EventAck)
async def wait_feedback(
    order_id: uuid.UUID,
    payload: s.WaitFeedbackIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.record_wait_feedback(db, order_id, customer, payload.bucket)


@router.get("/orders/{order_id}", response_model=s.OrderOut)
async def get_order(
    order_id: uuid.UUID,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    order = await CarevoService.get_order(db, order_id, customer)
    wait_estimate = await CarevoService.shadow_estimate(db, order_id)
    # total_amount is what was charged; the discount is stored alongside it
    # (migration 010) precisely so the original can be reconstructed here rather
    # than being lost the moment the order is placed.
    total = float(order.total_amount or 0)
    discount = float(order.discount_amount or 0)
    return {
        "id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
        "pickup_code": order.pickup_code,
        "total_amount": total,
        "original_amount": round(total + discount, 2),
        "discount_amount": discount,
        "final_amount": total,
        "wait_estimate": wait_estimate,
        "items": [
            {
                "id": it.id,
                "menu_item_id": it.menu_item_id,
                "name_snap": it.name_snap,
                "price_snap": float(it.price_snap or 0),
                "quantity": it.quantity,
                "customizations": it.customizations,
                "item_notes": it.item_notes,
            }
            for it in order.items
        ],
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


@router.post("/orders/{order_id}/advance", response_model=s.OrderOut)
async def advance_order(
    order_id: uuid.UUID,
    payload: s.AdvanceStatusIn | None = None,
    _staff=Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    target = payload.status if payload else None
    order = await CarevoService.advance_status(db, order_id, target)
    total = float(order.total_amount or 0)
    discount = float(order.discount_amount or 0)
    return {
        "id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
        "pickup_code": order.pickup_code,
        "total_amount": total,
        "original_amount": round(total + discount, 2),
        "discount_amount": discount,
        "final_amount": total,
        "items": [
            {
                "id": it.id,
                "menu_item_id": it.menu_item_id,
                "name_snap": it.name_snap,
                "price_snap": float(it.price_snap or 0),
                "quantity": it.quantity,
                "customizations": it.customizations,
                "item_notes": it.item_notes,
            }
            for it in order.items
        ],
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


# ------------------------------ Payment ------------------------------------
@router.post("/payment/webhook")
async def payment_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    from app.modules.carevo_payments.gateway import get_gateway
    from app.modules.carevo_customer.model import CustomerOrder
    from sqlalchemy import select, text

    body = await request.body()

    # Signature headers differ per gateway, so read both and let the gateway
    # decide which it needs. Cashfree additionally signs a timestamp header.
    h = request.headers
    signature = (
        h.get("x-webhook-signature")            # Cashfree
        or h.get("x-razorpay-signature")        # Razorpay
        or h.get("X-Razorpay-Signature")
    )
    timestamp = h.get("x-webhook-timestamp")    # Cashfree only

    gw = get_gateway()
    # The raw bytes are what gets verified — re-serialising the parsed JSON
    # would reorder keys and invalidate the digest.
    if not gw.verify_webhook_signature(body, signature, timestamp=timestamp):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        data = {}

    # Gateway-specific parsing lives in the gateway, not here. Adding ZohoPay
    # later means one new parse_webhook, not another branch in this endpoint.
    evt = gw.parse_webhook(body, data)

    order = None
    if evt.our_order_id:
        try:
            res = await db.execute(
                select(CustomerOrder).where(CustomerOrder.id == evt.our_order_id))
            order = res.scalars().first()
        except Exception:
            # our_order_id came off the wire; a non-UUID must 404, not 500.
            await db.rollback()
            order = None
    if order is None and evt.gateway_order_id:
        row = (await db.execute(text("""
            SELECT customer_order_id FROM payment_transactions
            WHERE gateway_order_id = :goid LIMIT 1
        """), {"goid": evt.gateway_order_id})).first()
        if row:
            res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == row[0]))
            order = res.scalars().first()

    if order is None:
        raise HTTPException(status_code=404, detail="Order for webhook not found")

    if evt.outcome == "PAID":
        # The EXISTING cascade, unchanged: pickup code, points accrual, PE
        # events, WS broadcast, FCM push. Webhook-triggered instead of
        # staff-tapped — that is the whole difference.
        order = await CarevoService.mark_paid(
            db, order,
            gateway_payment_id=evt.gateway_payment_id,
            method=evt.method,
            raw_payload=data or None,
        )
        # No human gate: a paid order is an accepted order. Staff are pushed
        # about it and may reject, but the order never waits to be noticed.
        order = await CarevoService.auto_receive(db, order)
        # Tell the outlet a new paid order landed. Best-effort — a push failure
        # must never affect a payment that already succeeded.
        try:
            from app.modules.push.service import PushService
            await PushService.notify_outlet_new_order(db, order)
        except Exception:
            await db.rollback()
        return {"ok": True, "outcome": "PAID", "status": order.status,
                "pickup_code": order.pickup_code}

    if evt.outcome == "FAILED":
        # Previously there was no failure path at all: a failed payment left the
        # order sitting in CREATED/PENDING forever, indistinguishable from one
        # the customer simply never paid.
        await CarevoService.mark_payment_failed(
            db, order,
            gateway_payment_id=evt.gateway_payment_id,
            method=evt.method,
            raw_payload=data or None,
        )
        return {"ok": True, "outcome": "FAILED", "status": order.status}

    # PENDING / UNKNOWN: acknowledge so the gateway stops retrying, but change
    # nothing. Guessing "probably paid" here is how free orders happen.
    return {"ok": True, "outcome": evt.outcome, "status": order.status}


@router.post("/payment/simulate", response_model=s.SimulatePaymentOut)
async def simulate_payment(
    payload: s.SimulatePaymentIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    # STUB ONLY — guard behind PAYMENT_GATEWAY=stub
    if settings.PAYMENT_GATEWAY != "stub":
        raise HTTPException(status_code=403, detail="Simulation disabled (real gateway active)")
    order = await CarevoService.get_order(db, payload.order_id, customer)
    order = await CarevoService.mark_paid(db, order, method=payload.method)
    return {"status": order.status, "pickup_code": order.pickup_code}
