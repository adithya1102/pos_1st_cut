"""Business logic for CareVo Skip (customer pre-order / pickup)."""
from __future__ import annotations

import json
import math
import secrets
import string
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
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
from app.modules.prediction import events as pe

# --- OTP rate limiter -------------------------------------------------------
# NOTE: single-process limiter; use Redis in prod
_otp_hits: dict[str, list[float]] = defaultdict(list)
# Per-IP limiter for public owner self-signup (POST /register), same pattern.
_register_hits: dict[str, list[float]] = defaultdict(list)

# Default categories seeded for every self-registered outlet, so the owner has
# real options in the dish form's category picker immediately. Order = display.
DEFAULT_CATEGORIES = ["Starters", "Mains", "Sides", "Desserts", "Beverages"]

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
            "SELECT id, location_name, city, latitude, longitude, upi_id FROM outlets "
            "WHERE is_visible = true"
        ))).fetchall()
        out = []
        for r in rows:
            oid, name, city, o_lat, o_lng, upi_id = r
            distance = None
            if lat is not None and lng is not None and o_lat is not None and o_lng is not None:
                distance = CarevoService._haversine_km(lat, lng, float(o_lat), float(o_lng))
            out.append({
                "id": oid,
                "name": name,
                "address": city,
                "is_open": True,
                "distance_km": distance,
                "upi_id": upi_id,
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
                   mi.is_veg, mi.is_available, mi.prep_time_minutes, mi.tags,
                   mi.image_url
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
                    "image_url": r.image_url,
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

        # PE Step 3 (FR-C1/C2): persist travel context on the order.
        if any(v is not None for v in (payload.transport_mode, payload.origin_lat,
                                       payload.origin_lng, payload.origin_source)):
            await db.execute(text("""
                UPDATE customer_orders SET transport_mode=:tm, origin_lat=:la,
                       origin_lng=:ln, origin_source=:os WHERE id=:id
            """), {"tm": payload.transport_mode, "la": payload.origin_lat,
                   "ln": payload.origin_lng, "os": payload.origin_source,
                   "id": str(order.id)})

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

        # FR-E1: ORDER_CREATED in the SAME transaction as the order insert.
        await pe.write_event(
            db, order.id, pe.ORDER_CREATED,
            actor_type="customer", actor_id=customer.id, source="tap",
            outlet_id=order.outlet_id,
            payload={
                "items": [
                    {"menu_item_id": str(i.menu_item_id), "quantity": i.quantity}
                    for i in payload.items
                ],
                # origin/transport are populated once Step 3 (customer_app) lands.
                "transport_mode": getattr(payload, "transport_mode", None),
                "origin_lat": getattr(payload, "origin_lat", None),
                "origin_lng": getattr(payload, "origin_lng", None),
                "origin_source": getattr(payload, "origin_source", None),
            },
        )
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

    # -------------------- PE Step 3: customer events -----------------------
    @staticmethod
    async def _owned_order_row(db: AsyncSession, order_id, customer):
        row = (await db.execute(text(
            "SELECT id, outlet_id, customer_id FROM customer_orders WHERE id = :o"
        ), {"o": str(order_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        if str(row.customer_id) != str(customer.id):
            raise HTTPException(status_code=403, detail="Not your order")
        return row

    @staticmethod
    async def _has_event(db: AsyncSession, order_id, event_type) -> bool:
        return (await db.execute(text(
            "SELECT 1 FROM order_events WHERE order_id = :o AND event_type = :t LIMIT 1"
        ), {"o": str(order_id), "t": event_type})).first() is not None

    @staticmethod
    async def record_departed(db, order_id, customer, lat, lng) -> dict:
        row = await CarevoService._owned_order_row(db, order_id, customer)
        # FR-C3: whichever fires first (tap or inferred) wins — idempotent.
        if await CarevoService._has_event(db, order_id, pe.CUSTOMER_DEPARTED):
            return {"ok": True, "recorded": False, "detail": "already departed"}
        await pe.write_event(
            db, order_id, pe.CUSTOMER_DEPARTED, actor_type="customer",
            actor_id=customer.id, source="tap", outlet_id=row.outlet_id,
            payload={"lat": lat, "lng": lng})
        await db.commit()
        return {"ok": True, "recorded": True}

    @staticmethod
    async def record_location_ping(db, order_id, customer, lat, lng, accuracy_m, speed_mps) -> dict:
        row = await CarevoService._owned_order_row(db, order_id, customer)
        last = (await db.execute(text(
            "SELECT occurred_at, payload FROM order_events WHERE order_id = :o "
            "AND event_type = 'LOCATION_PING' ORDER BY seq DESC LIMIT 1"
        ), {"o": str(order_id)})).first()
        if last is not None:
            lp = last.payload if isinstance(last.payload, dict) else json.loads(last.payload)
            dt_s = (datetime.now(timezone.utc) - last.occurred_at).total_seconds()
            dist_m = float("inf")
            if lp.get("lat") is not None and lp.get("lng") is not None:
                dist_m = CarevoService._haversine_km(
                    float(lp["lat"]), float(lp["lng"]), float(lat), float(lng)) * 1000.0
            # FR-E5 / NFR-7: reject unless ≥ 90s OR ≥ 300m since the last ping.
            if dt_s < 90 and dist_m < 300:
                return {"ok": True, "recorded": False, "detail": "throttled"}
        await pe.write_event(
            db, order_id, pe.LOCATION_PING, actor_type="customer",
            actor_id=customer.id, source="system", outlet_id=row.outlet_id,
            payload={"lat": lat, "lng": lng, "accuracy_m": accuracy_m, "speed_mps": speed_mps})
        await db.commit()
        return {"ok": True, "recorded": True}

    @staticmethod
    async def record_arrived(db, order_id, customer, accuracy_m, source) -> dict:
        row = await CarevoService._owned_order_row(db, order_id, customer)
        if await CarevoService._has_event(db, order_id, pe.CUSTOMER_ARRIVED):
            return {"ok": True, "recorded": False, "detail": "already arrived"}
        await pe.write_event(
            db, order_id, pe.CUSTOMER_ARRIVED, actor_type="customer",
            actor_id=customer.id, source=("geofence" if source == "geofence" else "tap"),
            outlet_id=row.outlet_id, payload={"accuracy_m": accuracy_m})
        await db.commit()
        return {"ok": True, "recorded": True}

    @staticmethod
    async def record_wait_feedback(db, order_id, customer, bucket) -> dict:
        row = await CarevoService._owned_order_row(db, order_id, customer)
        if await CarevoService._has_event(db, order_id, pe.WAIT_FEEDBACK):
            return {"ok": True, "recorded": False, "detail": "already submitted"}
        await pe.write_event(
            db, order_id, pe.WAIT_FEEDBACK, actor_type="customer",
            actor_id=customer.id, source="tap", outlet_id=row.outlet_id,
            payload={"bucket": bucket})
        await db.commit()
        return {"ok": True, "recorded": True}

    # ---------------------------- Payment ----------------------------------
    @staticmethod
    @staticmethod
    async def _expire_stale_pickups(
        db: AsyncSession, *, outlet_id=None, order_id=None
    ) -> int:
        """Check-on-read expiry: any live/waiting order untouched for longer than
        PICKUP_TTL_MINUTES auto-transitions to ABANDONED, freeing its pickup_code.
        Done in SQL (now()/interval vs the timestamptz column) to avoid naive-vs-
        aware datetime bugs. Commits its own maintenance UPDATE. Returns rowcount.
        Scope to one outlet or one order; at least one must be given.
        """
        clauses = [
            "status = ANY(:live)",
            "updated_at < now() - make_interval(mins => :ttl)",
        ]
        params = {
            "live": list(_LIVE_STATUSES),
            "ttl": settings.PICKUP_TTL_MINUTES,
        }
        if outlet_id is not None:
            clauses.append("outlet_id = :oid")
            params["oid"] = str(outlet_id)
        if order_id is not None:
            clauses.append("id = :iid")
            params["iid"] = str(order_id)
        rows = (await db.execute(text(
            "UPDATE customer_orders SET status='ABANDONED', updated_at=now() "
            "WHERE " + " AND ".join(clauses) + " RETURNING id, outlet_id"
        ), params)).fetchall()
        if rows:
            # FR-E1: one ORDER_ABANDONED per expired order, same transaction.
            for r in rows:
                await pe.write_event(
                    db, r.id, pe.ORDER_ABANDONED,
                    actor_type="system", source="system", outlet_id=r.outlet_id,
                    payload={"reason": "pickup_ttl_expired",
                             "ttl_minutes": settings.PICKUP_TTL_MINUTES},
                )
            await db.commit()
        return len(rows)

    @staticmethod
    async def _generate_pickup_code(db: AsyncSession, outlet_id) -> str:
        # Free up any expired codes for this outlet first.
        await CarevoService._expire_stale_pickups(db, outlet_id=outlet_id)
        # Digits 2-9 only: no visually ambiguous chars (0/O, 1/I/l) and easy to
        # type on a numeric keypad at verify time. 8^6 = 262k codes, and
        # uniqueness is only needed among an outlet's LIVE orders (a handful).
        # Existing issued codes are unaffected — this only changes new ones.
        alphabet = "23456789"
        for _ in range(30):
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            # Unique among LIVE orders for this outlet. ABANDONED is excluded so
            # an expired order's code is immediately reusable.
            row = (await db.execute(text("""
                SELECT 1 FROM customer_orders
                WHERE outlet_id = :oid AND pickup_code = :code
                  AND status NOT IN ('COMPLETED','CANCELLED','ABANDONED')
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
        txn.updated_at = datetime.now(timezone.utc)

        order.payment_status = "PAID"
        order.status = "PAID"
        if not order.pickup_code:
            order.pickup_code = await CarevoService._generate_pickup_code(db, order.outlet_id)
        order.updated_at = datetime.now(timezone.utc)

        # FR-E1: ORDER_PAID in the same transaction as the PAID transition.
        await pe.write_event(
            db, order.id, pe.ORDER_PAID,
            actor_type="staff", source="tap", outlet_id=order.outlet_id,
            payload={"method": method or "upi_manual"},
        )
        # PE Step 2: the owner has a single app and won't tap kitchen states, so
        # the system INFERS the kitchen lifecycle. Payment confirmation is taken
        # as acceptance + prep start. source='inferred' → excluded from kitchen
        # training as ground truth (FR-E2), but anchors the twin/prediction.
        await pe.write_event(
            db, order.id, pe.ORDER_ACCEPTED,
            actor_type="system", source="inferred", outlet_id=order.outlet_id,
            payload={"derived_from": "mark_paid"},
        )
        await pe.write_event(
            db, order.id, pe.PREP_STARTED,
            actor_type="system", source="inferred", outlet_id=order.outlet_id,
            payload={"derived_from": "mark_paid"},
        )
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
        order.updated_at = datetime.now(timezone.utc)
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
        # Expire this order first if its pickup window lapsed, so a stale code
        # can't be verified (and doesn't cost the staff a failed attempt).
        await CarevoService._expire_stale_pickups(db, order_id=order_id)

        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.is_locked:
            raise HTTPException(status_code=423, detail={"verified": False, "locked": True})

        if order.status.upper() == "ABANDONED":
            return {
                "verified": False,
                "order_id": order.id,
                "status": "ABANDONED",
            }

        code_ok = bool(order.pickup_code) and order.pickup_code.upper() == pickup_code.strip().upper()
        status_ok = order.status.upper() in _LIVE_STATUSES

        if code_ok and status_ok:
            order.status = "COMPLETED"
            order.pickup_verified_at = datetime.now(timezone.utc)
            order.updated_at = datetime.now(timezone.utc)
            # FR-E1: PICKUP_VERIFIED in the same transaction as COMPLETED.
            await pe.write_event(
                db, order.id, pe.PICKUP_VERIFIED,
                actor_type="staff", source="tap", outlet_id=order.outlet_id,
            )
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
        order.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(order)
        attempts_remaining = max(0, 3 - order.failed_attempts)
        return {"verified": False, "attempts_remaining": attempts_remaining, "locked": locked}

    # ------------------------- Owner App (staff) ---------------------------
    @staticmethod
    async def get_owner_outlet(db: AsyncSession, outlet_id: uuid.UUID) -> dict:
        row = (await db.execute(text(
            "SELECT id, location_name, is_visible FROM outlets WHERE id = :oid"
        ), {"oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        return {"id": row[0], "location_name": row[1], "is_visible": bool(row[2])}

    @staticmethod
    async def set_outlet_visibility(
        db: AsyncSession, outlet_id: uuid.UUID, is_visible: bool
    ) -> dict:
        row = (await db.execute(text(
            "UPDATE outlets SET is_visible = :v WHERE id = :oid RETURNING id, is_visible"
        ), {"v": is_visible, "oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        await db.commit()
        return {"id": row[0], "is_visible": bool(row[1])}

    # SELECT clause shared by the owner list + single-item reads, so responses
    # are shaped identically everywhere.
    _OWNER_ITEM_COLS = """
        mi.id, mi.name, mi.is_available, mi.is_active, mi.base_price,
        mi.is_veg, mi.prep_time_minutes, mi.image_url,
        c.id AS category_id, c.name AS category_name
    """

    @staticmethod
    def _owner_item_dict(r) -> dict:
        return {
            "id": r.id,
            "name": r.name,
            "is_available": bool(r.is_available),
            "is_active": bool(r.is_active),
            "base_price": float(r.base_price) if r.base_price is not None else 0.0,
            "is_veg": bool(r.is_veg),
            "prep_time_minutes": r.prep_time_minutes,
            "image_url": r.image_url,
            "category_id": r.category_id,
            "category_name": r.category_name,
        }

    @staticmethod
    async def list_owner_menu_items(db: AsyncSession, outlet_id: uuid.UUID) -> list[dict]:
        """Flat list of the outlet's latest-menu items (no category grouping)."""
        rows = (await db.execute(text(f"""
            SELECT {CarevoService._OWNER_ITEM_COLS}
            FROM menu_items mi
            JOIN categories c ON c.id = mi.category_id
            JOIN menus m ON m.id = c.menu_id
            WHERE m.outlet_id = :oid AND m.is_latest = true
              AND mi.is_active = true
            ORDER BY mi.name
        """), {"oid": str(outlet_id)})).fetchall()
        return [CarevoService._owner_item_dict(r) for r in rows]

    @staticmethod
    async def _owner_item_or_404(db: AsyncSession, item_id: uuid.UUID, outlet_id: uuid.UUID) -> dict:
        """Read one item scoped to the caller's outlet, or 404."""
        r = (await db.execute(text(f"""
            SELECT {CarevoService._OWNER_ITEM_COLS}
            FROM menu_items mi
            JOIN categories c ON c.id = mi.category_id
            JOIN menus m ON m.id = c.menu_id
            WHERE mi.id = :iid AND m.outlet_id = :oid
            LIMIT 1
        """), {"iid": str(item_id), "oid": str(outlet_id)})).first()
        if not r:
            raise HTTPException(status_code=404, detail="Menu item not found for this outlet")
        return CarevoService._owner_item_dict(r)

    @staticmethod
    async def _category_of_outlet_or_400(db: AsyncSession, category_id: uuid.UUID, outlet_id: uuid.UUID) -> None:
        """Guard: a category must belong to the caller's latest menu."""
        ok = (await db.execute(text("""
            SELECT 1 FROM categories c
            JOIN menus m ON m.id = c.menu_id
            WHERE c.id = :cid AND m.outlet_id = :oid AND m.is_latest = true
            LIMIT 1
        """), {"cid": str(category_id), "oid": str(outlet_id)})).first()
        if not ok:
            raise HTTPException(status_code=400, detail="Category not found for this outlet")

    @staticmethod
    async def list_owner_categories(db: AsyncSession, outlet_id: uuid.UUID) -> list[dict]:
        rows = (await db.execute(text("""
            SELECT c.id, c.name FROM categories c
            JOIN menus m ON m.id = c.menu_id
            WHERE m.outlet_id = :oid AND m.is_latest = true
            ORDER BY c.name
        """), {"oid": str(outlet_id)})).fetchall()
        return [{"id": r.id, "name": r.name} for r in rows]

    @staticmethod
    async def create_menu_item(db: AsyncSession, outlet_id: uuid.UUID, payload) -> dict:
        await CarevoService._category_of_outlet_or_400(db, payload.category_id, outlet_id)
        row = (await db.execute(text("""
            INSERT INTO menu_items
                (id, category_id, name, base_price, is_veg, prep_time_minutes,
                 image_url, is_active, is_available, created_at)
            VALUES
                (gen_random_uuid(), :cid, :name, :price, :veg, :prep,
                 :img, true, true, now())
            RETURNING id
        """), {
            "cid": str(payload.category_id),
            "name": payload.name,
            "price": payload.base_price,
            "veg": payload.is_veg,
            "prep": payload.prep_time_minutes,
            "img": payload.image_url,
        })).first()
        await db.commit()
        return await CarevoService._owner_item_or_404(db, row[0], outlet_id)

    @staticmethod
    async def update_menu_item(db: AsyncSession, item_id: uuid.UUID, outlet_id: uuid.UUID, payload) -> dict:
        # Ownership guard first (404 if not the caller's item).
        await CarevoService._owner_item_or_404(db, item_id, outlet_id)
        fields = payload.model_dump(exclude_unset=True)
        if "category_id" in fields and fields["category_id"] is not None:
            await CarevoService._category_of_outlet_or_400(db, fields["category_id"], outlet_id)
        if not fields:
            return await CarevoService._owner_item_or_404(db, item_id, outlet_id)
        # Build a parameterized SET clause from whitelisted columns only.
        allowed = {"name", "base_price", "category_id", "is_veg",
                   "prep_time_minutes", "image_url", "is_available"}
        sets, params = [], {"iid": str(item_id)}
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = :{k}")
            params[k] = str(v) if k == "category_id" and v is not None else v
        await db.execute(text(f"UPDATE menu_items SET {', '.join(sets)} WHERE id = :iid"), params)
        await db.commit()
        return await CarevoService._owner_item_or_404(db, item_id, outlet_id)

    @staticmethod
    async def delete_menu_item(db: AsyncSession, item_id: uuid.UUID, outlet_id: uuid.UUID) -> dict:
        # Soft delete: deactivate rather than DROP, preserving order history refs.
        await CarevoService._owner_item_or_404(db, item_id, outlet_id)
        row = (await db.execute(text(
            "UPDATE menu_items SET is_active = false, is_available = false "
            "WHERE id = :iid RETURNING id, is_active"
        ), {"iid": str(item_id)})).first()
        await db.commit()
        return {"ok": True, "id": row[0], "is_active": bool(row[1])}

    # ------------------------- Owner self-signup ---------------------------
    @staticmethod
    def check_register_rate_limit(client_ip: str) -> None:
        """Per-IP cap, mirroring check_otp_rate_limit (single-process; Redis in prod)."""
        now = time.time()
        window = 3600.0
        hits = [t for t in _register_hits[client_ip] if now - t < window]
        if len(hits) >= settings.REGISTER_RATE_LIMIT_PER_HOUR:
            _register_hits[client_ip] = hits
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many registration attempts, try later",
            )
        hits.append(now)
        _register_hits[client_ip] = hits

    @staticmethod
    async def register_owner(db: AsyncSession, payload, client_ip: str) -> dict:
        """Public owner self-signup. Bootstraps organization + outlet
        (pending_verification, hidden) + owner user + latest menu + a default
        category, as ONE atomic transaction: every INSERT runs before a single
        commit, and ANY failure rolls the whole thing back — no orphaned rows.
        """
        from app.core.security import get_password_hash

        CarevoService.check_register_rate_limit(client_ip)

        taken = (await db.execute(
            text("SELECT 1 FROM users WHERE username = :u LIMIT 1"),
            {"u": payload.username},
        )).first()
        if taken:
            raise HTTPException(status_code=409, detail="Username already taken")

        try:
            org_id = (await db.execute(text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES (gen_random_uuid(), :n, now()) RETURNING id"
            ), {"n": payload.restaurant_name})).scalar()

            outlet_id = (await db.execute(text(
                "INSERT INTO outlets (id, location_name, city, latitude, longitude, "
                "  geofence_radius_meters, organization_id, verification_status, is_visible, "
                "  upi_id, created_at) "
                "VALUES (gen_random_uuid(), :ln, :city, :lat, :lng, 100, :org, "
                "        'pending_verification', false, :upi, now()) RETURNING id"
            ), {
                "ln": payload.restaurant_name, "city": payload.city,
                "lat": payload.latitude, "lng": payload.longitude, "org": str(org_id),
                "upi": payload.upi_id,
            })).scalar()

            await db.execute(text(
                "INSERT INTO users (id, username, hashed_password, is_active, outlet_id, created_at) "
                "VALUES (gen_random_uuid(), :u, :pw, true, :oid, now())"
            ), {"u": payload.username, "pw": get_password_hash(payload.password), "oid": str(outlet_id)})

            menu_id = (await db.execute(text(
                "INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at) "
                "VALUES (gen_random_uuid(), :oid, 'v1', true, now()) RETURNING id"
            ), {"oid": str(outlet_id)})).scalar()

            # Seed a sensible default set so the owner can add dishes immediately
            # (the dish form's category picker has real options from the start).
            # Owners can still add/rename their own categories on top of these.
            for _pos, _name in enumerate(DEFAULT_CATEGORIES):
                await db.execute(text(
                    "INSERT INTO categories (id, menu_id, name, created_at) "
                    "VALUES (gen_random_uuid(), :mid, :name, now())"
                ), {"mid": str(menu_id), "name": _name})

            # Single commit: all rows persist together, or none do.
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            # Includes the users.username UNIQUE race → clean rollback, no orphans.
            await db.rollback()
            raise HTTPException(status_code=500, detail="Registration failed")

        return {
            "outlet_id": outlet_id,
            "username": payload.username,
            "verification_status": "pending_verification",
            "message": "Registered. Pending admin verification before your outlet is visible to customers.",
        }

    @staticmethod
    async def set_item_availability(
        db: AsyncSession, item_id: uuid.UUID, outlet_id: uuid.UUID, is_available: bool
    ) -> dict:
        # Ownership guard: item must belong to a latest menu of the caller's outlet.
        owns = (await db.execute(text("""
            SELECT 1 FROM menu_items mi
            JOIN categories c ON c.id = mi.category_id
            JOIN menus m ON m.id = c.menu_id
            WHERE mi.id = :iid AND m.outlet_id = :oid
            LIMIT 1
        """), {"iid": str(item_id), "oid": str(outlet_id)})).first()
        if not owns:
            raise HTTPException(status_code=404, detail="Menu item not found for this outlet")
        row = (await db.execute(text(
            "UPDATE menu_items SET is_available = :v WHERE id = :iid RETURNING id, is_available"
        ), {"v": is_available, "iid": str(item_id)})).first()
        await db.commit()
        return {"id": row[0], "is_available": bool(row[1])}

    @staticmethod
    async def list_active_orders(db: AsyncSession, outlet_id: uuid.UUID) -> list[dict]:
        """Active customer_orders for the outlet, newest first. NAME-FREE."""
        # Sweep expired pickups so the queue never shows stale orders.
        await CarevoService._expire_stale_pickups(db, outlet_id=outlet_id)
        orders = (await db.execute(text("""
            SELECT id, status, payment_status, is_locked, total_amount, created_at
            FROM customer_orders
            WHERE outlet_id = :oid AND status NOT IN ('COMPLETED','CANCELLED','ABANDONED')
            ORDER BY created_at DESC
        """), {"oid": str(outlet_id)})).fetchall()
        if not orders:
            return []
        order_ids = [str(o.id) for o in orders]
        items = (await db.execute(text("""
            SELECT id, customer_order_id, name_snap, quantity
            FROM customer_order_items
            WHERE customer_order_id = ANY(:ids)
            ORDER BY created_at
        """), {"ids": order_ids})).fetchall()
        by_order: dict = defaultdict(list)
        for it in items:
            by_order[str(it.customer_order_id)].append(
                {"id": it.id, "name": it.name_snap, "quantity": it.quantity}
            )
        return [
            {
                "order_id": o.id,
                "status": o.status,
                "payment_status": o.payment_status,
                "is_locked": bool(o.is_locked),
                "total_amount": float(o.total_amount) if o.total_amount is not None else 0.0,
                "created_at": o.created_at,
                "items": by_order.get(str(o.id), []),
            }
            for o in orders
        ]

    @staticmethod
    async def mark_order_paid_by_staff(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID
    ) -> dict:
        """Manual-tick payment confirmation (UPI-intent MVP). Staff confirm the
        payment landed in their UPI app; this flips the order to PAID, issues the
        pickup_code, and broadcasts — surfacing the order as confirmed to the
        customer. Ownership-scoped and idempotent (via mark_paid)."""
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order or str(order.outlet_id) != str(outlet_id):
            raise HTTPException(status_code=404, detail="Order not found for this outlet")
        order = await CarevoService.mark_paid(db, order, method="upi_manual")
        return {
            "order_id": order.id,
            "status": order.status,
            "payment_status": order.payment_status,
            "pickup_code": order.pickup_code,
        }

    @staticmethod
    async def notify_order(
        db: AsyncSession,
        order_id: uuid.UUID,
        outlet_id: uuid.UUID,
        notify_type: str,
        item_id: Optional[uuid.UUID],
    ) -> dict:
        valid = {"ready_now", "delayed_10", "item_unavailable"}
        if notify_type not in valid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid type. Must be one of: {sorted(valid)}",
            )

        # Order must exist and belong to the caller's outlet.
        order = (await db.execute(text(
            "SELECT id, outlet_id FROM customer_orders WHERE id = :oid"
        ), {"oid": str(order_id)})).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if str(order.outlet_id) != str(outlet_id):
            raise HTTPException(status_code=403, detail="Order does not belong to your outlet")

        item_name: Optional[str] = None
        resolved_item_id: Optional[uuid.UUID] = None

        if notify_type == "item_unavailable":
            if item_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="item_id is required when type is 'item_unavailable'",
                )
            line = (await db.execute(text("""
                SELECT id, name_snap FROM customer_order_items
                WHERE id = :iid AND customer_order_id = :oid
            """), {"iid": str(item_id), "oid": str(order_id)})).first()
            if not line:
                raise HTTPException(
                    status_code=400,
                    detail="item_id is not a line item of this order",
                )
            resolved_item_id = line.id
            item_name = line.name_snap
        # For ready_now / delayed_10, item_id is ignored (kept null).

        messages = {
            "ready_now": "Your order is ready for pickup.",
            "delayed_10": "Your order is delayed by about 10 minutes.",
            "item_unavailable": f"'{item_name}' is unavailable and won't be prepared.",
        }
        payload = {
            "event": "notify",
            "order_id": str(order_id),
            "type": notify_type,
            "item_id": str(resolved_item_id) if resolved_item_id else None,
            "item_name": item_name,
            "message": messages[notify_type],
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        # PE Step 2: "Ready now" is the one genuine readiness signal the owner
        # already gives (no separate kitchen taps), so it emits ORDER_READY.
        # item_unavailable is recorded too (affects composition + hold tolerance).
        if notify_type == "ready_now":
            await pe.write_event(
                db, order_id, pe.ORDER_READY,
                actor_type="staff", source="tap", outlet_id=outlet_id,
            )
            await db.commit()
        elif notify_type == "item_unavailable":
            await pe.write_event(
                db, order_id, pe.ITEM_UNAVAILABLE,
                actor_type="staff", source="tap", outlet_id=outlet_id,
                payload={"item_id": str(resolved_item_id) if resolved_item_id else None},
            )
            await db.commit()

        # Best-effort delivery: delivered reflects whether any socket is connected.
        delivered = bool(customer_manager.active_connections.get(str(order_id)))
        try:
            await customer_manager.send_order_update(str(order_id), payload)
        except Exception:
            delivered = False

        return {
            "ok": True,
            "delivered": delivered,
            "type": notify_type,
            "item_id": resolved_item_id,
            "item_name": item_name,
        }
