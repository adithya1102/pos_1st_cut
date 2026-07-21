"""Business logic for CareVo Skip (customer pre-order / pickup)."""
from __future__ import annotations

import math
import secrets
import string
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.websocket_manager import customer_manager, pos_manager
from app.modules.customers.model import Customer
from app.modules.carevo_customer.model import (
    CustomerOrder,
    CustomerOrderItem,
    PaymentTransaction,
)
from app.modules.carevo_payments.gateway import get_gateway

# --- OTP rate limiter -------------------------------------------------------
# NOTE: single-process limiter; use Redis in prod
_otp_hits: dict[str, list[float]] = defaultdict(list)

# Status progression for the pickup flow
_PROGRESSION = ["RECEIVED", "PREPARING", "READY"]
_LIVE_STATUSES = {"PAID", "RECEIVED", "PREPARING", "READY"}


class CarevoService:
    # ------------------------------ OTP ------------------------------------
    @staticmethod
    def check_otp_rate_limit(phone_number: str) -> None:
        now = time.time()
        window = 3600.0
        hits = [t for t in _otp_hits[phone_number] if now - t < window]
        if len(hits) >= settings.OTP_RATE_LIMIT_PER_HOUR:
            _otp_hits[phone_number] = hits
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests, try later",
            )
        hits.append(now)
        _otp_hits[phone_number] = hits

    @staticmethod
    def request_otp(phone_number: str) -> dict:
        CarevoService.check_otp_rate_limit(phone_number)
        # Stub: no SMS actually sent.
        return {"request_id": uuid.uuid4().hex, "stub": True}

    @staticmethod
    async def verify_otp(db: AsyncSession, phone_number: str, otp: str) -> Customer:
        if settings.OTP_STUB_MODE:
            if otp != settings.OTP_STUB_CODE:
                raise HTTPException(status_code=401, detail="Invalid OTP")
        else:
            # No real OTP provider wired yet.
            raise HTTPException(status_code=501, detail="OTP verification not configured")

        res = await db.execute(select(Customer).where(Customer.phone_number == phone_number))
        customer = res.scalars().first()
        if not customer:
            customer = Customer(phone_number=phone_number)
            db.add(customer)
            await db.commit()
            await db.refresh(customer)
        return customer

    # --------------------------- Discovery ---------------------------------
    @staticmethod
    def _haversine_km(lat1, lon1, lat2, lon2) -> float:
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return round(2 * r * math.asin(math.sqrt(a)), 3)

    @staticmethod
    async def list_outlets(db: AsyncSession, lat: Optional[float], lng: Optional[float]) -> list[dict]:
        rows = (await db.execute(text(
            "SELECT id, location_name, city, latitude, longitude FROM outlets"
        ))).fetchall()
        out = []
        for r in rows:
            oid, name, city, o_lat, o_lng = r
            distance = None
            if lat is not None and lng is not None and o_lat is not None and o_lng is not None:
                distance = CarevoService._haversine_km(lat, lng, float(o_lat), float(o_lng))
            out.append({
                "id": oid,
                "name": name,
                "address": city,
                "is_open": True,
                "distance_km": distance,
            })
        if lat is not None and lng is not None:
            out.sort(key=lambda x: (x["distance_km"] is None, x["distance_km"] or 0))
        return out

    # ------------------------------ Menu -----------------------------------
    @staticmethod
    async def get_menu(db: AsyncSession, outlet_id: uuid.UUID) -> dict:
        # Categories of the latest menu for this outlet, with available/active items.
        rows = (await db.execute(text("""
            SELECT c.id AS cat_id, c.name AS cat_name,
                   mi.id AS item_id, mi.name AS item_name, mi.base_price,
                   mi.is_veg, mi.is_available, mi.prep_time_minutes, mi.tags
            FROM categories c
            JOIN menus m ON m.id = c.menu_id
            LEFT JOIN menu_items mi
                   ON mi.category_id = c.id
                  AND mi.is_active = true
                  AND mi.is_available = true
            WHERE m.outlet_id = :oid AND m.is_latest = true
            ORDER BY c.name, mi.name
        """), {"oid": str(outlet_id)})).fetchall()

        # modifiers per item for customizations
        item_ids = [r.item_id for r in rows if r.item_id is not None]
        mods: dict = defaultdict(list)
        if item_ids:
            mrows = (await db.execute(text("""
                SELECT menu_item_id, modifier_name FROM item_modifiers
                WHERE menu_item_id = ANY(:ids)
            """), {"ids": [str(i) for i in item_ids]})).fetchall()
            for mr in mrows:
                mods[str(mr.menu_item_id)].append(mr.modifier_name)

        cats: dict = {}
        order: list = []
        for r in rows:
            key = str(r.cat_id)
            if key not in cats:
                cats[key] = {"id": r.cat_id, "name": r.cat_name, "items": []}
                order.append(key)
            if r.item_id is not None:
                cats[key]["items"].append({
                    "id": r.item_id,
                    "name": r.item_name,
                    "base_price": float(r.base_price) if r.base_price is not None else 0.0,
                    "is_veg": bool(r.is_veg),
                    "is_available": bool(r.is_available),
                    "prep_time_minutes": r.prep_time_minutes,
                    "tags": r.tags,
                    "customizations": mods.get(str(r.item_id), []),
                })
        return {"outlet_id": outlet_id, "categories": [cats[k] for k in order]}

    # ----------------------------- Orders ----------------------------------
    @staticmethod
    async def create_order(db: AsyncSession, customer: Customer, payload) -> dict:
        # Snapshot name + price from menu_items.
        item_ids = [str(i.menu_item_id) for i in payload.items]
        rows = (await db.execute(text("""
            SELECT id, name, base_price, is_available, is_active
            FROM menu_items WHERE id = ANY(:ids)
        """), {"ids": item_ids})).fetchall()
        by_id = {str(r.id): r for r in rows}

        order = CustomerOrder(
            customer_id=customer.id,
            outlet_id=payload.outlet_id,
            status="CREATED",
            payment_status="PENDING",
            customer_notes=payload.customer_notes,
            total_amount=0,
        )
        db.add(order)
        await db.flush()  # assign order.id

        total = 0.0
        for line in payload.items:
            mi = by_id.get(str(line.menu_item_id))
            if not mi:
                raise HTTPException(status_code=400, detail=f"Unknown menu item {line.menu_item_id}")
            if not (mi.is_available and mi.is_active):
                raise HTTPException(status_code=409, detail=f"Item unavailable: {mi.name}")
            price = float(mi.base_price) if mi.base_price is not None else 0.0
            total += price * line.quantity
            db.add(CustomerOrderItem(
                customer_order_id=order.id,
                menu_item_id=line.menu_item_id,
                name_snap=mi.name,
                price_snap=price,
                quantity=line.quantity,
                customizations=line.customizations,
                item_notes=line.item_notes,
            ))

        order.total_amount = round(total, 2)

        # Create gateway order (stub / razorpay-shaped)
        gw = get_gateway()
        g_order = gw.create_order(order.total_amount, currency="INR", receipt=str(order.id))

        db.add(PaymentTransaction(
            customer_order_id=order.id,
            gateway=g_order.gateway,
            gateway_order_id=g_order.gateway_order_id,
            amount=order.total_amount,
            currency=g_order.currency,
            status="CREATED",
            method=None,
        ))
        await db.commit()

        return {
            "id": order.id,
            "status": "CREATED",
            "total_amount": order.total_amount,
            "payment": {
                "gateway": g_order.gateway,
                "gateway_order_id": g_order.gateway_order_id,
                "amount": g_order.amount,
                "currency": g_order.currency,
                "key_id": g_order.key_id,
            },
        }

    @staticmethod
    async def get_order(db: AsyncSession, order_id: uuid.UUID, customer: Customer) -> CustomerOrder:
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if str(order.customer_id) != str(customer.id):
            raise HTTPException(status_code=403, detail="Not your order")
        return order

    # ---------------------------- Payment ----------------------------------
    @staticmethod
    async def _generate_pickup_code(db: AsyncSession, outlet_id) -> str:
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(30):
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            # Unique among LIVE orders for this outlet (matches partial unique index).
            row = (await db.execute(text("""
                SELECT 1 FROM customer_orders
                WHERE outlet_id = :oid AND pickup_code = :code
                  AND status NOT IN ('COMPLETED','CANCELLED')
                LIMIT 1
            """), {"oid": str(outlet_id), "code": code})).first()
            if not row:
                return code
        raise HTTPException(status_code=500, detail="Could not allocate pickup code")

    @staticmethod
    async def mark_paid(
        db: AsyncSession,
        order: CustomerOrder,
        *,
        gateway_payment_id: Optional[str] = None,
        gateway_signature: Optional[str] = None,
        method: Optional[str] = None,
        raw_payload: Optional[dict] = None,
    ) -> CustomerOrder:
        """Idempotent PAID transition shared by webhook + simulate."""
        # Idempotency on gateway_payment_id.
        if gateway_payment_id:
            existing = (await db.execute(text("""
                SELECT customer_order_id FROM payment_transactions
                WHERE gateway_payment_id = :pid AND status = 'PAID' LIMIT 1
            """), {"pid": gateway_payment_id})).first()
            if existing:
                res = await db.execute(
                    select(CustomerOrder).where(CustomerOrder.id == existing[0])
                )
                return res.scalars().first() or order

        if order.payment_status == "PAID":
            return order  # already settled

        gw = get_gateway()
        pay_id = gateway_payment_id or gw.make_payment_id()

        # Find the pending transaction (created at order time) or make a new one.
        res = await db.execute(
            select(PaymentTransaction)
            .where(PaymentTransaction.customer_order_id == order.id)
            .order_by(PaymentTransaction.created_at.desc())
        )
        txn = res.scalars().first()
        if txn is None:
            txn = PaymentTransaction(customer_order_id=order.id, amount=order.total_amount)
            db.add(txn)

        sig = gateway_signature or gw.sign_payment(txn.gateway_order_id or "", pay_id)
        txn.gateway = txn.gateway or gw.name
        txn.gateway_payment_id = pay_id
        txn.gateway_signature = sig
        txn.method = method or txn.method or "upi"
        txn.status = "PAID"
        txn.raw_payload = raw_payload
        txn.updated_at = datetime.utcnow()

        order.payment_status = "PAID"
        order.status = "PAID"
        if not order.pickup_code:
            order.pickup_code = await CarevoService._generate_pickup_code(db, order.outlet_id)
        order.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(order)

        await CarevoService._broadcast_status(order)
        return order

    @staticmethod
    async def advance_status(db: AsyncSession, order_id: uuid.UUID, target: Optional[str] = None) -> CustomerOrder:
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if target:
            new_status = target.upper()
            if new_status not in _PROGRESSION:
                raise HTTPException(status_code=400, detail="Invalid target status")
        else:
            cur = order.status.upper()
            if cur in ("CREATED", "PAID"):
                new_status = "RECEIVED"
            elif cur in _PROGRESSION:
                idx = _PROGRESSION.index(cur)
                new_status = _PROGRESSION[min(idx + 1, len(_PROGRESSION) - 1)]
            else:
                new_status = "RECEIVED"

        order.status = new_status
        order.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(order)
        await CarevoService._broadcast_status(order)
        return order

    @staticmethod
    async def _broadcast_status(order: CustomerOrder) -> None:
        """Reuse the in-memory WS layer to push Skip status changes."""
        payload = {
            "event": "SKIP_ORDER_STATUS",
            "order_id": str(order.id),
            "order_status": order.status,
            "payment_status": order.payment_status,
            "pickup_code": order.pickup_code,
        }
        try:
            await customer_manager.send_order_update(str(order.id), payload)
        except Exception:
            pass
        try:
            await pos_manager.broadcast_to_outlet(str(order.outlet_id), payload)
        except Exception:
            pass

    # ------------------------------ POS ------------------------------------
    @staticmethod
    async def verify_pickup(db: AsyncSession, order_id: uuid.UUID, pickup_code: str) -> dict:
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.is_locked:
            raise HTTPException(status_code=423, detail={"verified": False, "locked": True})

        code_ok = bool(order.pickup_code) and order.pickup_code.upper() == pickup_code.strip().upper()
        status_ok = order.status.upper() in _LIVE_STATUSES

        if code_ok and status_ok:
            order.status = "COMPLETED"
            order.pickup_verified_at = datetime.utcnow()
            order.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(order)
            await CarevoService._broadcast_status(order)
            return {"verified": True, "order_id": order.id, "status": "COMPLETED"}

        # Wrong code (or non-live status) — count as a failed attempt.
        order.failed_attempts = (order.failed_attempts or 0) + 1
        locked = False
        if order.failed_attempts >= 3:
            order.is_locked = True
            locked = True
        order.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(order)
        attempts_remaining = max(0, 3 - order.failed_attempts)
        return {"verified": False, "attempts_remaining": attempts_remaining, "locked": locked}
