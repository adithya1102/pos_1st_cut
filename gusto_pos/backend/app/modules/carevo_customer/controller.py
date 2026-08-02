"""CareVo Skip customer-facing routes (mounted under /api/v1)."""
from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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
        },
    }


# ---------------------------- Discovery ------------------------------------
@router.get("/outlets", response_model=list[s.OutletOut])
async def list_outlets(
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    _: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.list_outlets(db, lat, lng)


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
    return {
        "id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
        "pickup_code": order.pickup_code,
        "total_amount": float(order.total_amount or 0),
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
    return {
        "id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
        "pickup_code": order.pickup_code,
        "total_amount": float(order.total_amount or 0),
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
    signature = request.headers.get("x-razorpay-signature") or request.headers.get(
        "X-Razorpay-Signature"
    )
    gw = get_gateway()
    if not gw.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        data = {}

    # Extract razorpay-shaped identifiers (best-effort across payload shapes).
    entity = (
        data.get("payload", {}).get("payment", {}).get("entity", {})
        if isinstance(data.get("payload"), dict)
        else {}
    )
    gateway_order_id = entity.get("order_id") or data.get("gateway_order_id")
    gateway_payment_id = entity.get("id") or data.get("gateway_payment_id")
    method = entity.get("method") or data.get("method")
    order_id = data.get("order_id") or data.get("customer_order_id")

    order = None
    if order_id:
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
    if order is None and gateway_order_id:
        row = (await db.execute(text("""
            SELECT customer_order_id FROM payment_transactions
            WHERE gateway_order_id = :goid LIMIT 1
        """), {"goid": gateway_order_id})).first()
        if row:
            res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == row[0]))
            order = res.scalars().first()

    if order is None:
        raise HTTPException(status_code=404, detail="Order for webhook not found")

    order = await CarevoService.mark_paid(
        db, order,
        gateway_payment_id=gateway_payment_id,
        method=method,
        raw_payload=data or None,
    )
    return {"ok": True, "status": order.status, "pickup_code": order.pickup_code}


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
