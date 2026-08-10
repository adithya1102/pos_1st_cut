"""Business logic for CareVo Skip (customer pre-order / pickup)."""
from __future__ import annotations

import json
import math
import secrets
import string
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.websocket_manager import customer_manager, pos_manager
from app.modules.customers.model import Customer
from app.modules.carevo_customer.model import (
    Coupon,
    CustomerOrder,
    CustomerOrderItem,
    PaymentTransaction,
    PointTransaction,
)
from app.modules.carevo_payments.gateway import get_gateway
from app.modules.prediction import events as pe
# Safe at module level: promotions.service imports only its own schema, so this
# closes no cycle (promotions.controller reaches back into carevo_customer.deps,
# never into this module).
from app.modules.promotions.service import PromotionService

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

    @staticmethod
    async def verify_firebase_token(db: AsyncSession, id_token: str) -> Customer:
        """Exchange a verified Firebase phone-auth token for a Customer row.

        Independent of OTP_STUB_MODE: this path never trusts a client-supplied
        code, so it is safe to run with the stub still enabled for dev builds.
        """
        from app.modules.carevo_customer.firebase import (
            find_phone_variants,
            normalize_phone,
            verify_phone_token,
        )

        if not settings.FIREBASE_ENABLED:
            raise HTTPException(
                status_code=501,
                detail="Firebase authentication is not enabled on this deployment",
            )

        phone, _uid = await verify_phone_token(id_token)
        canonical = normalize_phone(phone)

        # Match legacy spellings too, so pre-Firebase rows (and their order
        # history) are reused instead of duplicated under the E.164 form.
        res = await db.execute(
            select(Customer).where(Customer.phone_number.in_(find_phone_variants(phone)))
        )
        customer = res.scalars().first()

        if not customer:
            customer = Customer(phone_number=canonical)
            db.add(customer)
            await db.commit()
            await db.refresh(customer)
        elif customer.phone_number != canonical:
            # Upgrade the stored number to E.164 now that it is provider-verified.
            customer.phone_number = canonical
            await db.commit()
            await db.refresh(customer)

        return customer

    @staticmethod
    async def verify_google_token(db: AsyncSession, id_token: str) -> Customer:
        """Exchange a verified Firebase Google-provider token for a Customer row.

        Standalone identity: the resulting customer has NO phone number. The app
        renders it as "—" until the customer verifies a phone separately, at
        which point the phone-auth path fills it in on the same row.

        Matching order is google_uid first, then email. The uid is the stable
        key (an email can be reassigned by a Workspace admin); email is the
        fallback that reunites a Google login with a row created by an earlier
        Google sign-in before uid was stored, and backfills the uid onto it.
        """
        from app.modules.carevo_customer.firebase import verify_google_token

        if not settings.FIREBASE_ENABLED:
            raise HTTPException(
                status_code=501,
                detail="Firebase authentication is not enabled on this deployment",
            )

        email, uid, name = await verify_google_token(id_token)

        res = await db.execute(select(Customer).where(Customer.google_uid == uid))
        customer = res.scalars().first()

        if not customer:
            res = await db.execute(
                select(Customer).where(func.lower(Customer.email) == email)
            )
            customer = res.scalars().first()

        if not customer:
            # No phone: this is the standalone-identity case the nullable
            # phone_number column (migration 008) exists for.
            customer = Customer(email=email, google_uid=uid, name=name)
            db.add(customer)
            await db.commit()
            await db.refresh(customer)
            return customer

        # Existing row — reconcile it with what Google just told us.
        changed = False
        if customer.google_uid != uid:
            customer.google_uid = uid
            changed = True
        if customer.email != email:
            customer.email = email
            changed = True
        if name and not customer.name:
            customer.name = name
            changed = True
        if changed:
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
    async def list_outlets(
        db: AsyncSession,
        lat: Optional[float],
        lng: Optional[float],
        city: Optional[str] = None,
    ) -> list[dict]:
        rows = (await db.execute(text(
            "SELECT id, location_name, city, latitude, longitude, upi_id, image_url "
            "FROM outlets "
            "WHERE is_visible = true AND deactivated_at IS NULL "
            # CAST for the same reason as list_outlets in carevo_admin: with a
            # NULL bind Postgres cannot infer the parameter type from
            # `:city IS NULL` alone. Case-insensitive so the city picked from
            # /customer/areas matches regardless of stored capitalisation.
            "  AND (CAST(:city AS varchar) IS NULL "
            "       OR lower(city) = lower(CAST(:city AS varchar)))"
        ), {"city": city})).fetchall()

        # Offer summary for the inline chip (migration 016). ONE query for the
        # whole list — a per-card lookup would be N round trips on the first
        # screen the customer sees. "*" holds the platform-wide campaigns, which
        # reach every outlet including those with no offer of their own.
        offers = await PromotionService.offer_summary_by_outlet(db)
        platform = offers.get("*")

        out = []
        for r in rows:
            oid, name, city, o_lat, o_lng, upi_id, image_url = r
            distance = None
            if lat is not None and lng is not None and o_lat is not None and o_lng is not None:
                distance = CarevoService._haversine_km(lat, lng, float(o_lat), float(o_lng))
            summary = offers.get(str(oid)) or platform
            out.append({
                "id": oid,
                "name": name,
                "address": city,
                "is_open": True,
                "distance_km": distance,
                "upi_id": upi_id,
                "image_url": image_url,
                "offer_count": (summary or {}).get("count", 0),
                "offer_text": (summary or {}).get("text"),
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

        gross = round(total, 2)

        # Coupon (migration 010). Applied BEFORE the gateway order is created so
        # the customer is only ever charged the discounted amount — settling the
        # full amount and refunding the difference would be a second money path
        # to get wrong.
        discount = 0.0
        promotion_label: Optional[str] = None
        wants_coupon = bool(getattr(payload, "coupon_code", None))
        wants_promotion = bool(
            getattr(payload, "promotion_id", None)
            or getattr(payload, "promotion_code", None)
        )

        # No stacking in V1. Rejected outright rather than quietly honouring one
        # of the two: a customer who supplies both and is charged for one has no
        # way to tell which was ignored. The DB backs this up as well —
        # idx_promo_redemption_one_per_order allows a single promotion per order.
        if wants_coupon and wants_promotion:
            raise HTTPException(
                status_code=422,
                detail="Use either a coupon or an offer on an order, not both.",
            )

        if wants_coupon:
            discount = await CarevoService._consume_points_coupon(
                db, customer, order_id=order.id, gross=gross,
                code=payload.coupon_code,
            )
        elif wants_promotion:
            # Promotions (migration 016). Runs in this same open transaction, so
            # a failure below rolls the redemption back and the offer stays
            # claimable — identical discipline to _consume_points_coupon.
            applied = await PromotionService.apply_to_order(
                db,
                customer_id=customer.id,
                outlet_id=payload.outlet_id,
                order_id=order.id,
                gross=gross,
                promotion_id=getattr(payload, "promotion_id", None),
                code=getattr(payload, "promotion_code", None),
            )
            discount = applied["discount_amount"]
            promotion_label = applied["label"]

        order.discount_amount = discount
        # Never below zero: a ₹100 coupon on an ₹80 order settles at ₹0, and the
        # unused ₹20 is not carried anywhere (single-use means single-use).
        order.total_amount = round(max(gross - discount, 0.0), 2)

        # Create gateway order (stub / razorpay-shaped)
        gw = get_gateway()
        # Awaited now that the interface is async — a real gateway is a network
        # call, and running it synchronously would block the event loop.
        # `receipt` carries OUR order id, which Cashfree echoes back on the
        # webhook so no correlation table is needed.
        g_order = await gw.create_order(
            order.total_amount, currency="INR", receipt=str(order.id),
            customer={
                "id": str(customer.id),
                "phone": customer.phone_number,
                "email": customer.email,
                "name": customer.name,
            },
        )

        db.add(PaymentTransaction(
            customer_order_id=order.id,
            gateway=g_order.gateway,
            gateway_order_id=g_order.gateway_order_id,
            amount=order.total_amount,
            currency=g_order.currency,
            status="CREATED",
            method=None,
        ))
        self_session_id = g_order.payment_session_id

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
                # What the Cashfree Flutter SDK opens checkout with. Null for
                # the Razorpay-shaped stub, which opens on order_id + key_id.
                "payment_session_id": self_session_id,
            },
            # The struck-through-price breakdown, computed here rather than in
            # the app: `gross` is the pre-discount figure and only this function
            # has ever known it.
            "original_amount": gross,
            "discount_amount": discount,
            "final_amount": order.total_amount,
            "promotion_label": promotion_label,
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

    @staticmethod
    async def shadow_estimate(db: AsyncSession, order_id) -> Optional[dict]:
        """§16 wide range for the customer. Compute-on-read if the twin is stale
        and the order is still live (§17). Best-effort — never raises to the caller."""
        live = (await db.execute(text(
            "SELECT status FROM customer_orders WHERE id = :o"), {"o": str(order_id)})).scalar()
        twin = (await db.execute(text(
            "SELECT inputs, stale_after FROM order_twin WHERE order_id = :o"
        ), {"o": str(order_id)})).first()
        stale = twin is None or (twin.stale_after and twin.stale_after < datetime.now(timezone.utc))
        if live in _LIVE_STATUSES and stale:
            try:
                from app.modules.prediction.service import PredictionService
                res = await PredictionService.recompute_twin(db, order_id)
                if res:
                    lo, hi = res["shadow_range_min"]
                    return {"low_min": lo, "high_min": hi, "approximate": res.get("degraded", True)}
            except Exception:
                await db.rollback()
        if twin and twin.inputs:
            inp = twin.inputs if isinstance(twin.inputs, dict) else json.loads(twin.inputs)
            sr = inp.get("shadow_range_min")
            if sr:
                return {"low_min": sr[0], "high_min": sr[1],
                        "approximate": inp.get("travel_source") == "haversine_fallback"}
        return None

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
        # FR-C4: 150m geofence is inferred server-side so the client stays a dumb
        # location streamer. Emit CUSTOMER_ARRIVED once, when the ping lands inside
        # the ring around the outlet (idempotent — a prior tap/geofence wins).
        arrived = False
        oc = (await db.execute(text(
            "SELECT latitude, longitude FROM outlets WHERE id = :o"
        ), {"o": str(row.outlet_id)})).first()
        if oc and oc.latitude is not None and oc.longitude is not None:
            dist_m = CarevoService._haversine_km(
                float(lat), float(lng), float(oc.latitude), float(oc.longitude)) * 1000.0
            if dist_m <= 150.0 and not await CarevoService._has_event(
                    db, order_id, pe.CUSTOMER_ARRIVED):
                await pe.write_event(
                    db, order_id, pe.CUSTOMER_ARRIVED, actor_type="customer",
                    actor_id=customer.id, source="geofence", outlet_id=row.outlet_id,
                    payload={"accuracy_m": accuracy_m, "distance_m": round(dist_m, 1)})
                arrived = True
        await db.commit()
        return {"ok": True, "recorded": True, "detail": "arrived" if arrived else None}

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
            # PE Step 4: score terminal (abandoned) orders too, best-effort.
            for r in rows:
                try:
                    from app.modules.prediction.service import PredictionService
                    await PredictionService.compute_outcome(db, r.id)
                except Exception:
                    await db.rollback()
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

        # Loyalty accrual (migration 010), in the SAME transaction as the PAID
        # transition: points are earned iff the payment is recorded, and the two
        # can never diverge through a partial failure.
        await CarevoService._accrue_points(db, order)

        await db.commit()
        await db.refresh(order)

        await CarevoService._broadcast_status(order, db)

        # PE Step 4 (shadow mode): compute the order twin once accepted. Runs in
        # its own transaction AFTER payment is committed, wrapped so a prediction
        # failure can never roll back or break the payment (FR-M1: promise only
        # after ORDER_ACCEPTED, which mark_paid just emitted).
        try:
            from app.modules.prediction.service import PredictionService
            await PredictionService.recompute_twin(db, order.id)
        except Exception:
            await db.rollback()
        return order

    # Rejecting is allowed right up until the food is ready. Past READY the
    # order is made and sitting on the counter — "we can't do this one" is no
    # longer true, and the customer may already be walking over.
    REJECTABLE_STATUSES = {"PAID", "RECEIVED", "PREPARING"}

    @staticmethod
    async def auto_receive(db: AsyncSession, order: CustomerOrder) -> CustomerOrder:
        """PAID -> RECEIVED with no human gate.

        There is no Accept step by design: a paid order is accepted. Staff get a
        push and can REJECT if something is genuinely wrong, but the order is
        never parked waiting for someone to notice it.

        mark_paid is left completely untouched — it still emits the inferred
        ORDER_ACCEPTED/PREP_STARTED the prediction engine anchors on, at exactly
        the same moment it always did. This only moves the visible status on.
        """
        if (order.status or "").upper() != "PAID":
            return order  # already moved on, or never paid
        return await CarevoService.advance_status(db, order.id, "RECEIVED")

    @staticmethod
    async def reject_order(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        *, reason: Optional[str] = None, actor_user_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Staff refuse a paid order -> CANCELLED + ORDER_REJECTED.

        ORDER_REJECTED is a distinct event on purpose. ORDER_ABANDONED already
        exists and means the TTL sweeper expired an order nobody paid for;
        PAYMENT_FAILED means the gateway declined. This one is a human saying
        no to money already taken — the only one of the three that obliges a
        refund, and the only one worth surfacing to the customer as a decision
        rather than an accident.

        Refunds are deliberately OUT of scope: handled manually outside the app.
        """
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order or str(order.outlet_id) != str(outlet_id):
            raise HTTPException(status_code=404, detail="Order not found for this outlet")

        current = (order.status or "").upper()
        if current == "CANCELLED":
            # Idempotent: a double-tap is not an error.
            return {"order_id": order.id, "status": current, "already": True}
        if current not in CarevoService.REJECTABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This order is already ready for pickup and can no longer be "
                    "rejected." if current in ("READY", "COMPLETED")
                    else f"An order in {current} cannot be rejected."
                ),
            )

        order.status = "CANCELLED"
        order.updated_at = datetime.now(timezone.utc)

        await pe.write_event(
            db, order.id, pe.ORDER_REJECTED,
            actor_type="staff", source="tap", outlet_id=order.outlet_id,
            actor_id=actor_user_id,
            payload={"reason": reason, "from_status": current},
        )
        await db.commit()
        await db.refresh(order)

        # Same choke point every other transition uses, so the customer's WS
        # banner and the FCM push both fire from one place.
        await CarevoService._broadcast_status(order, db)
        return {
            "order_id": order.id,
            "status": order.status,
            "already": False,
            "reason": reason,
        }

    @staticmethod
    async def mark_payment_failed(
        db: AsyncSession,
        order: CustomerOrder,
        *,
        gateway_payment_id: Optional[str] = None,
        method: Optional[str] = None,
        raw_payload: Optional[dict] = None,
    ) -> CustomerOrder:
        """Record a gateway-reported payment failure.

        The mirror of mark_paid, and deliberately much smaller: nothing accrues,
        no pickup code is issued, no ORDER_ACCEPTED/PREP_STARTED is inferred.
        Only the payment outcome is recorded.

        Idempotent and one-way — never downgrades an order that is already PAID.
        Gateways retry, and retries arrive out of order; a late FAILED webhook
        for a payment that later succeeded must not un-pay a settled order.
        """
        if order.payment_status == "PAID":
            return order

        res = await db.execute(
            select(PaymentTransaction)
            .where(PaymentTransaction.customer_order_id == order.id)
            .order_by(PaymentTransaction.created_at.desc())
        )
        txn = res.scalars().first()
        if txn is None:
            txn = PaymentTransaction(customer_order_id=order.id, amount=order.total_amount)
            db.add(txn)
        txn.gateway = txn.gateway or get_gateway().name
        if gateway_payment_id:
            txn.gateway_payment_id = gateway_payment_id
        txn.method = method or txn.method
        txn.status = "FAILED"
        txn.raw_payload = raw_payload
        txn.updated_at = datetime.now(timezone.utc)

        # The ORDER stays CREATED: the basket is still valid and the customer
        # can retry payment. Only payment_status carries the failure, so a
        # retry needs no resurrection logic.
        order.payment_status = "FAILED"
        order.updated_at = datetime.now(timezone.utc)

        await pe.write_event(
            db, order.id, pe.PAYMENT_FAILED,
            actor_type="system", source="webhook", outlet_id=order.outlet_id,
            payload={"method": method, "gateway_payment_id": gateway_payment_id},
        )
        await db.commit()
        await db.refresh(order)
        await CarevoService._broadcast_status(order, db)
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
        await CarevoService._broadcast_status(order, db)
        return order

    @staticmethod
    async def _broadcast_status(order: CustomerOrder, db: AsyncSession = None) -> None:
        """Reuse the in-memory WS layer to push Skip status changes.

        Also the single hook for FCM order-status pushes (migration 014): every
        transition already funnels through here, so notifications reuse this
        choke point instead of re-deriving which statuses changed. Wrapped so a
        push failure can never affect the order.
        """
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

        # FCM push for the same transition. Best-effort and fully swallowed:
        # a notification must never fail or roll back the order it describes.
        # Inert (logged as 'skipped') until PUSH_ENABLED + a service account
        # are configured, so this is safe to ship before credentials exist.
        if db is not None:
            try:
                from app.modules.push.service import PushService
                await PushService.notify_order_status(db, order)
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
            await CarevoService._broadcast_status(order, db)
            # PE Step 4: score the terminal order (trust + outcome), best-effort.
            try:
                from app.modules.prediction.service import PredictionService
                await PredictionService.compute_outcome(db, order.id)
            except Exception:
                await db.rollback()
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
            "SELECT id, location_name, is_visible, image_url FROM outlets WHERE id = :oid"
        ), {"oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        return {
            "id": row[0], "location_name": row[1],
            "is_visible": bool(row[2]), "image_url": row[3],
        }

    @staticmethod
    async def set_outlet_image(
        db: AsyncSession, outlet_id: uuid.UUID, image_url: Optional[str]
    ) -> dict:
        """Store the outlet storefront photo URL (migration 011).

        The upload itself happens client-side against Cloudinary's unsigned
        endpoint - the same pipeline dish images already use - so the backend
        only ever stores the resulting URL and never handles image bytes.
        Passing null clears the photo, returning the card to its fallback glyph.
        """
        url = (image_url or "").strip() or None
        row = (await db.execute(text(
            "UPDATE outlets SET image_url = :u WHERE id = :oid "
            "RETURNING id, location_name, is_visible, image_url"
        ), {"u": url, "oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        await db.commit()
        return {
            "id": row[0], "location_name": row[1],
            "is_visible": bool(row[2]), "image_url": row[3],
        }

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

        # Resolve the city BEFORE anything is written (migration 013).
        # Exactly one of city / requested_city is accepted — the schema enforces
        # that. A named city must already be active in the canonical list, so
        # free-text spellings can no longer enter `outlets.city`; a requested one
        # is recorded as pending for admin approval further down.
        city_name = None
        requested_city = (getattr(payload, "requested_city", None) or "").strip()
        if payload.city:
            row = (await db.execute(text(
                "SELECT name FROM cities WHERE lower(name) = lower(:n) "
                "AND status = 'active' LIMIT 1"
            ), {"n": payload.city.strip()})).first()
            if not row:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "That city is not available yet. Pick one from the list, "
                        "or request a new city."
                    ),
                )
            # Store the canonical spelling, not whatever casing was submitted.
            city_name = row[0]
        else:
            city_name = requested_city

        try:
            org_id = (await db.execute(text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES (gen_random_uuid(), :n, now()) RETURNING id"
            ), {"n": payload.restaurant_name})).scalar()

            outlet_id = (await db.execute(text(
                "INSERT INTO outlets (id, location_name, city, phone_number, latitude, longitude, "
                "  geofence_radius_meters, organization_id, verification_status, is_visible, "
                "  upi_id, created_at) "
                "VALUES (gen_random_uuid(), :ln, :city, :phone, :lat, :lng, 100, :org, "
                "        'pending_verification', false, :upi, now()) RETURNING id"
            ), {
                "ln": payload.restaurant_name, "city": city_name,
                "phone": (payload.phone_number or "").strip() or None,
                "lat": payload.latitude, "lng": payload.longitude, "org": str(org_id),
                "upi": payload.upi_id,
            })).scalar()

            # New-city request rides the SAME pending-approval pattern as outlet
            # verification: a row with status='pending' that an admin approves or
            # rejects, audited through admin_audit_logs. No second queue.
            #
            # ON CONFLICT DO NOTHING: if another owner already requested the same
            # city (or it exists rejected), do not duplicate the row — the outlet
            # still carries the name and rides the existing request's decision.
            if requested_city:
                await db.execute(text("""
                    INSERT INTO cities (name, status, requested_by_outlet_id)
                    VALUES (:n, 'pending', :oid)
                    ON CONFLICT (lower(name)) DO NOTHING
                """), {"n": requested_city, "oid": str(outlet_id)})

            # email lands on the USER row (migration 015): password recovery is
            # per-account, and an outlet can have several staff users.
            taken_email = (await db.execute(text(
                "SELECT 1 FROM users WHERE lower(email) = lower(:e) LIMIT 1"
            ), {"e": payload.email})).first()
            if taken_email:
                raise HTTPException(
                    status_code=409, detail="That email is already registered"
                )

            await db.execute(text(
                "INSERT INTO users (id, username, hashed_password, is_active, outlet_id, "
                "  email, created_at) "
                "VALUES (gen_random_uuid(), :u, :pw, true, :oid, :email, now())"
            ), {
                "u": payload.username, "pw": get_password_hash(payload.password),
                "oid": str(outlet_id), "email": payload.email.strip().lower(),
            })

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

    # Tombstone marker for a deleted account, written to google_uid.
    #
    # It has to go SOMEWHERE, because customers_identity_present CHECKs that
    # phone_number OR google_uid is non-null, and the row must survive to hold
    # order history together (customer_orders.customer_id is RESTRICT).
    #
    # google_uid rather than phone_number for two concrete reasons:
    #   * phone_number is varchar(20) — "deleted:" + a 36-char uuid is 44 chars
    #     and does not fit. google_uid is varchar(128).
    #   * putting it here lets phone_number be set to NULL, i.e. genuinely
    #     erased, which is the better privacy outcome anyway.
    # The uuid makes it unique by construction (google_uid has a partial unique
    # index) and "deleted:<uuid>" can never match a real Google UID, so no
    # sign-in path can find a tombstone and resurrect the dead account.
    DELETED_UID_PREFIX = "deleted:"

    @staticmethod
    def is_deleted_customer(google_uid: Optional[str]) -> bool:
        return bool(google_uid and google_uid.startswith(
            CarevoService.DELETED_UID_PREFIX))

    @staticmethod
    async def delete_my_account(db: AsyncSession, customer: Customer) -> dict:
        """Irreversibly erase the customer's personal data (Play Store requires
        an in-app deletion route for apps with accounts).

        NOT a row DELETE, and that is forced by the schema, not a preference:
        customer_orders.customer_id is RESTRICT, so deleting the row fails for
        anyone who has ever ordered — and cascading it would destroy the
        restaurants' revenue records along with the customer.

        So: anonymise in place. Every identifier is overwritten or nulled, the
        row survives only as an unusable tombstone holding the orders together.

        ERASED  — name, phone, email, google_uid, device token, points balance,
                  premium window, unspent coupons, notification history.
        RETAINED— order rows and their line items (business/tax records, as the
                  privacy policy states), plus points/promotion ledgers, which
                  carry ids and amounts but no personal data.

        Login is impossible afterwards: the tombstoned phone matches no real
        number and google_uid is gone, so neither sign-in path can find it.
        """
        cid = str(customer.id)

        # Personal content first, so a failure part-way cannot leave the
        # identity erased while their data lingers.
        await db.execute(text("DELETE FROM coupons WHERE customer_id = :c"), {"c": cid})
        await db.execute(
            text("DELETE FROM push_notifications WHERE customer_id = :c"), {"c": cid})

        row = (await db.execute(text("""
            UPDATE customers
            SET name = NULL,
                email = NULL,
                phone_number = NULL,
                fcm_token = NULL,
                fcm_token_updated_at = NULL,
                points_balance = 0,
                premium_until = NULL,
                google_uid = :prefix || id::text
            WHERE id = :c
            RETURNING id
        """), {"c": cid, "prefix": CarevoService.DELETED_UID_PREFIX})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")

        retained = (await db.execute(text(
            "SELECT count(*) FROM customer_orders WHERE customer_id = :c"), {"c": cid}
        )).scalar() or 0

        await db.commit()
        return {
            "ok": True,
            "deleted": True,
            "orders_retained": int(retained),
            "message": (
                "Your account and personal details have been deleted. "
                "Past order records are kept for the restaurants' tax and "
                "accounting obligations, and are no longer linked to you."
            ),
        }

    @staticmethod
    async def register_staff_push_token(
        db: AsyncSession, user_id: uuid.UUID, fcm_token: str
    ) -> dict:
        """Store a staff device token (migration 017). Last device wins, same
        one-token-per-account model customers already use."""
        await db.execute(text("""
            UPDATE users SET fcm_token = :t, fcm_token_updated_at = now()
            WHERE id = :uid
        """), {"t": fcm_token.strip(), "uid": str(user_id)})
        await db.commit()
        return {"ok": True, "registered": True}

    @staticmethod
    async def mark_items_unavailable(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        item_ids: list,
    ) -> dict:
        """Batch N/A: several line items, one staff action.

        Deliberately NOT one event for the batch. Each item gets its own
        ITEM_UNAVAILABLE event and its own push naming that dish, because:
          * the prediction engine reads composition per item;
          * "2 items unavailable" tells the customer nothing actionable.

        Does NOT touch the order total. The original paid order stands as-is;
        adjusting it here would be a second money path (refunds are manual and
        off-app by decision), and the customer's remedy is to place a NEW order
        for replacements.
        """
        # Ownership first — never leak whether an order id exists elsewhere.
        order = (await db.execute(text(
            "SELECT id, outlet_id FROM customer_orders WHERE id = :oid"
        ), {"oid": str(order_id)})).first()
        if not order or str(order.outlet_id) != str(outlet_id):
            raise HTTPException(status_code=404, detail="Order not found for this outlet")

        # Collapse duplicates but keep the submitted order for stable output.
        seen, wanted = set(), []
        for i in item_ids:
            if str(i) not in seen:
                seen.add(str(i))
                wanted.append(str(i))

        rows = (await db.execute(text("""
            SELECT id, name_snap FROM customer_order_items
            WHERE customer_order_id = :oid AND id = ANY(:ids)
        """), {"oid": str(order_id), "ids": wanted})).fetchall()
        found = {str(r.id): r.name_snap for r in rows}

        missing = [i for i in wanted if i not in found]
        if missing:
            # All-or-nothing: a checklist that half-applies is worse than one
            # that refuses, because staff cannot see which half took.
            raise HTTPException(
                status_code=400,
                detail=f"{len(missing)} of the selected items are not line items of this order",
            )

        now = datetime.now(timezone.utc)
        marked = []
        for iid in wanted:
            await pe.write_event(
                db, order_id, pe.ITEM_UNAVAILABLE,
                actor_type="staff", source="tap", outlet_id=outlet_id,
                payload={"item_id": iid, "batch_size": len(wanted)},
            )
        await db.commit()

        # WS first (instant in-app banner), then FCM for a backgrounded app.
        delivered_any = False
        for iid in wanted:
            name = found[iid]
            payload = {
                "event": "notify",
                "order_id": str(order_id),
                "type": "item_unavailable",
                "item_id": iid,
                "item_name": name,
                "message": f"'{name}' is unavailable and won't be prepared.",
                "ts": now.isoformat(),
            }
            delivered = bool(customer_manager.active_connections.get(str(order_id)))
            try:
                await customer_manager.send_order_update(str(order_id), payload)
            except Exception:
                delivered = False
            delivered_any = delivered_any or delivered
            marked.append({"item_id": iid, "name": name, "notified": delivered})

        # One push per item, naming the dish. Best-effort throughout.
        try:
            from app.modules.push.service import PushService, KIND_ITEM_UNAVAILABLE
            cust = (await db.execute(text(
                "SELECT customer_id FROM customer_orders WHERE id = :oid"
            ), {"oid": str(order_id)})).scalar()
            if cust:
                for iid in wanted:
                    await PushService.send(
                        db, customer_id=cust, kind=KIND_ITEM_UNAVAILABLE,
                        title="Item unavailable",
                        body=f"'{found[iid]}' can't be prepared. "
                             f"Tap to reorder something else.",
                        order_id=order_id,
                        data={"item_id": iid, "item_name": found[iid] or ""},
                    )
        except Exception:
            await db.rollback()

        return {
            "ok": True,
            "order_id": order_id,
            "marked": marked,
            "delivered": delivered_any,
        }

    # ==================== Profile / loyalty / coupons (010) ====================
    # Accrual rate: 0.10 points per Rs.20 spent, i.e. points = amount * 0.005.
    # A Rs.10,000 lifetime spend reaches the 50-point threshold, which mints a
    # Rs.100 coupon - 1% back. Constants live here so clients never hardcode them.
    POINTS_PER_RUPEE = 0.10 / 20.0
    REDEMPTION_THRESHOLD = 50.0
    REDEMPTION_VALUE_RUPEES = 100.0
    PREMIUM_TRIAL_DAYS = 60

    @staticmethod
    def _plan_label(premium_until: Optional[datetime]) -> str:
        """Derive the plan from premium_until. Never stored - see MeOut."""
        if premium_until is None:
            return "Free"
        # Rows written before 010 may come back naive; treat those as UTC rather
        # than raising on an aware/naive comparison.
        if premium_until.tzinfo is None:
            premium_until = premium_until.replace(tzinfo=timezone.utc)
        return "Premium" if premium_until > datetime.now(timezone.utc) else "Free"

    @staticmethod
    def _me_payload(customer: Customer) -> dict:
        return {
            "id": customer.id,
            "name": customer.name,
            "phone_number": customer.phone_number,
            "email": customer.email,
            "points_balance": float(customer.points_balance or 0),
            "premium_until": customer.premium_until,
            "plan": CarevoService._plan_label(customer.premium_until),
        }

    @staticmethod
    async def get_me(db: AsyncSession, customer: Customer) -> dict:
        return CarevoService._me_payload(customer)

    @staticmethod
    async def update_me(db: AsyncSession, customer: Customer, payload) -> dict:
        """Name only. Phone and email are verified identities, not client-settable."""
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name cannot be empty")
        customer.name = name
        await db.commit()
        await db.refresh(customer)
        return CarevoService._me_payload(customer)

    @staticmethod
    async def list_my_orders(
        db: AsyncSession, customer: Customer, limit: int = 50
    ) -> list[dict]:
        """The signed-in customer's own order history, newest first.

        Scoped by customer_id taken from the bearer token - never from a
        client-supplied id - so one customer can never read another's orders.
        """
        orders = (await db.execute(text("""
            SELECT co.id, co.outlet_id, o.location_name AS outlet_name,
                   co.status, co.payment_status, co.total_amount,
                   co.discount_amount, co.created_at
            FROM customer_orders co
            LEFT JOIN outlets o ON o.id = co.outlet_id
            WHERE co.customer_id = :cid
            ORDER BY co.created_at DESC
            LIMIT :limit
        """), {"cid": str(customer.id), "limit": limit})).fetchall()
        if not orders:
            return []

        order_ids = [str(o.id) for o in orders]
        items = (await db.execute(text("""
            SELECT customer_order_id, name_snap, quantity
            FROM customer_order_items
            WHERE customer_order_id = ANY(:ids)
            ORDER BY created_at
        """), {"ids": order_ids})).fetchall()
        by_order: dict = defaultdict(list)
        for it in items:
            by_order[str(it.customer_order_id)].append(
                {"name": it.name_snap, "quantity": it.quantity}
            )

        return [
            {
                "order_id": o.id,
                "outlet_id": o.outlet_id,
                "outlet_name": o.outlet_name,
                "status": o.status,
                "payment_status": o.payment_status,
                "total_amount": float(o.total_amount or 0),
                "discount_amount": float(o.discount_amount or 0),
                "created_at": o.created_at,
                "items": by_order.get(str(o.id), []),
            }
            for o in orders
        ]

    @staticmethod
    async def _accrue_points(db: AsyncSession, order: CustomerOrder) -> None:
        """Award points for a paid order. Called inside mark_paid's transaction.

        Earned on what was actually paid (total_amount, already net of any
        discount): a redeemed coupon should not also re-earn points on the part
        it paid for.
        """
        if order.customer_id is None:
            return
        amount = float(order.total_amount or 0)
        points = round(amount * CarevoService.POINTS_PER_RUPEE, 2)
        if points <= 0:
            return

        # Idempotency guard mirroring the partial unique index in migration 010:
        # mark_paid is itself idempotent, but a retry must never double-award.
        already = (await db.execute(text("""
            SELECT 1 FROM point_transactions
            WHERE order_id = :oid AND reason = 'ORDER_ACCRUAL' LIMIT 1
        """), {"oid": str(order.id)})).first()
        if already:
            return

        db.add(PointTransaction(
            customer_id=order.customer_id,
            order_id=order.id,
            points_delta=points,
            reason="ORDER_ACCRUAL",
        ))
        # Increment in SQL rather than read-modify-write: two orders settling at
        # the same moment must not clobber each other's award.
        await db.execute(text("""
            UPDATE customers SET points_balance = COALESCE(points_balance, 0) + :p
            WHERE id = :cid
        """), {"p": points, "cid": str(order.customer_id)})

    @staticmethod
    async def get_points(db: AsyncSession, customer: Customer) -> dict:
        rows = (await db.execute(text("""
            SELECT id, order_id, points_delta, reason, created_at
            FROM point_transactions
            WHERE customer_id = :cid
            ORDER BY created_at DESC
            LIMIT 50
        """), {"cid": str(customer.id)})).fetchall()
        balance = float(customer.points_balance or 0)
        return {
            "points_balance": balance,
            "redemption_threshold": CarevoService.REDEMPTION_THRESHOLD,
            "redemption_value_rupees": CarevoService.REDEMPTION_VALUE_RUPEES,
            "can_redeem": balance >= CarevoService.REDEMPTION_THRESHOLD,
            "transactions": [
                {
                    "id": r.id,
                    "order_id": r.order_id,
                    "points_delta": float(r.points_delta),
                    "reason": r.reason,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
        }

    @staticmethod
    def _make_coupon_code(prefix: str) -> str:
        """Unambiguous alphabet: no O/0/I/1, so a code read aloud survives."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        body = "".join(secrets.choice(alphabet) for _ in range(8))
        return prefix + "-" + body

    @staticmethod
    async def redeem_points(db: AsyncSession, customer: Customer) -> dict:
        """Spend REDEMPTION_THRESHOLD points to mint one Rs.100 discount coupon."""
        threshold = CarevoService.REDEMPTION_THRESHOLD

        # The conditional UPDATE is the whole concurrency guard: two simultaneous
        # redemptions cannot both pass, because the second sees the debited
        # balance and matches no row.
        debited = (await db.execute(text("""
            UPDATE customers
            SET points_balance = points_balance - :t
            WHERE id = :cid AND COALESCE(points_balance, 0) >= :t
            RETURNING points_balance
        """), {"t": threshold, "cid": str(customer.id)})).first()
        if not debited:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    "Not enough points. You need {:g} to redeem (you have {:g})."
                ).format(threshold, float(customer.points_balance or 0)),
            )

        coupon = Coupon(
            code=CarevoService._make_coupon_code("PTS"),
            customer_id=customer.id,
            kind=Coupon.KIND_POINTS_DISCOUNT,
            discount_amount=CarevoService.REDEMPTION_VALUE_RUPEES,
            status="ACTIVE",
        )
        db.add(coupon)
        db.add(PointTransaction(
            customer_id=customer.id,
            order_id=None,  # not tied to an order until the coupon is spent
            points_delta=-threshold,
            reason="COUPON_REDEMPTION",
        ))
        await db.commit()
        await db.refresh(coupon)
        await db.refresh(customer)

        return {
            "coupon": {
                "id": coupon.id,
                "code": coupon.code,
                "kind": coupon.kind,
                "discount_amount": float(coupon.discount_amount),
                "trial_days": coupon.trial_days,
                "status": coupon.status,
                "expires_at": coupon.expires_at,
                "created_at": coupon.created_at,
            },
            "points_balance": float(customer.points_balance or 0),
            "message": "Rs.{:g} coupon ready. Apply it at checkout.".format(
                CarevoService.REDEMPTION_VALUE_RUPEES
            ),
        }

    @staticmethod
    async def list_my_coupons(db: AsyncSession, customer: Customer) -> list[dict]:
        rows = (await db.execute(text("""
            SELECT id, code, kind, discount_amount, trial_days, status,
                   expires_at, created_at
            FROM coupons
            WHERE customer_id = :cid AND status = 'ACTIVE'
            ORDER BY created_at DESC
        """), {"cid": str(customer.id)})).fetchall()
        return [
            {
                "id": r.id,
                "code": r.code,
                "kind": r.kind,
                "discount_amount": float(r.discount_amount or 0),
                "trial_days": r.trial_days or 0,
                "status": r.status,
                "expires_at": r.expires_at,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    @staticmethod
    async def _consume_points_coupon(
        db: AsyncSession, customer: Customer, *, order_id, gross: float, code: str
    ) -> float:
        """Validate and burn a POINTS_DISCOUNT coupon; return the rupee discount.

        Runs inside create_order's open transaction, so a later failure there
        rolls the burn back with it and the coupon stays spendable.
        """
        code = (code or "").strip().upper()
        now = datetime.now(timezone.utc)

        # One UPDATE does lookup, ownership check, expiry check, status check and
        # the burn together - leaving no window between validating and spending.
        row = (await db.execute(text("""
            UPDATE coupons
            SET status = 'REDEEMED', redeemed_at = :now, redeemed_order_id = :oid
            WHERE code = :code
              AND kind = 'POINTS_DISCOUNT'
              AND status = 'ACTIVE'
              AND (customer_id IS NULL OR customer_id = :cid)
              AND (expires_at IS NULL OR expires_at > :now)
            RETURNING id, discount_amount
        """), {
            "now": now, "oid": str(order_id), "code": code, "cid": str(customer.id),
        })).first()

        if not row:
            # Deliberately one message for every failure mode (unknown / already
            # used / expired / someone else's): probing codes should not reveal
            # which of those is true.
            raise HTTPException(
                status_code=422, detail="That coupon code is not valid."
            )

        await db.execute(text(
            "UPDATE customer_orders SET coupon_id = :couid WHERE id = :oid"
        ), {"couid": str(row[0]), "oid": str(order_id)})

        # Cap at the order value, so the recorded discount is never larger than
        # what was actually taken off.
        return round(min(float(row[1] or 0), gross), 2)

    @staticmethod
    async def redeem_trial_coupon(db: AsyncSession, customer: Customer, payload) -> dict:
        """Redeem a PREMIUM_TRIAL coupon: extends premium_until by trial_days.

        No payment, no billing, no plan record - this grants a timestamp. Paid
        plans are a separate workstream and premium unlocks nothing yet.
        """
        code = (payload.code or "").strip().upper()
        now = datetime.now(timezone.utc)

        row = (await db.execute(text("""
            UPDATE coupons
            SET status = 'REDEEMED', redeemed_at = :now,
                customer_id = COALESCE(customer_id, CAST(:cid AS uuid))
            WHERE code = :code
              AND kind = 'PREMIUM_TRIAL'
              AND status = 'ACTIVE'
              AND (customer_id IS NULL OR customer_id = CAST(:cid AS uuid))
              AND (expires_at IS NULL OR expires_at > :now)
            RETURNING trial_days
        """), {"now": now, "code": code, "cid": str(customer.id)})).first()

        if not row:
            raise HTTPException(
                status_code=422, detail="That coupon code is not valid."
            )

        days = int(row[0] or CarevoService.PREMIUM_TRIAL_DAYS)
        # Extend from whichever is later: an unexpired window is added to rather
        # than thrown away, and a lapsed one restarts from today.
        base = customer.premium_until
        if base is not None and base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        start = base if (base is not None and base > now) else now
        new_until = start + timedelta(days=days)

        await db.execute(text(
            "UPDATE customers SET premium_until = :pu WHERE id = :cid"
        ), {"pu": new_until, "cid": str(customer.id)})
        await db.commit()
        await db.refresh(customer)

        return {
            "kind": Coupon.KIND_PREMIUM_TRIAL,
            "premium_until": customer.premium_until,
            "plan": CarevoService._plan_label(customer.premium_until),
            "message": "Premium trial active for {} days.".format(days),
        }

    @staticmethod
    async def check_cart_availability(
        db: AsyncSession, outlet_id: uuid.UUID, item_ids: list
    ) -> dict:
        """Re-check a cart against live menu state, BEFORE payment.

        Exists because the customer menu query filters `is_available = true`, so
        an item turned off after it was added simply vanishes from the menu -
        the already-populated cart keeps it, and nothing notices until
        create_order raises 409. This endpoint moves that discovery earlier, to
        a point where the customer can still fix it without having paid.

        Read-only and side-effect free: it never mutates the cart or the order.
        create_order remains the authority - this is a courtesy pre-check, not a
        replacement for server-side validation.
        """
        if not item_ids:
            return {"ok": True, "unavailable": []}

        ids = [str(i) for i in item_ids]
        rows = (await db.execute(text("""
            SELECT mi.id, mi.name, mi.is_available, mi.is_active
            FROM menu_items mi
            WHERE mi.id = ANY(:ids)
        """), {"ids": ids})).fetchall()

        found = {str(r.id): r for r in rows}
        unavailable = []
        for iid in ids:
            r = found.get(iid)
            if r is None:
                # Deleted from the menu entirely since it was added.
                unavailable.append({"menu_item_id": iid, "name": None})
            elif not (r.is_available and r.is_active):
                unavailable.append({"menu_item_id": iid, "name": r.name})

        return {"ok": not unavailable, "unavailable": unavailable}

    @staticmethod
    async def list_areas(db: AsyncSession) -> list[dict]:
        """Cities that actually have at least one orderable outlet.

        Derived from live outlet rows, never a hardcoded list: a city appears
        here only while it has >=1 visible, non-deactivated outlet, so picking
        one can never lead to an empty result. When the last outlet in a city is
        hidden or deactivated, the city disappears from the picker on its own.

        `outlets` has no locality/area column today (only `city`), so this
        returns city granularity. See migration 012 (proposed, not applied) for
        the smallest addition that would let this return localities too.
        """
        rows = (await db.execute(text("""
            SELECT city, count(*) AS outlet_count
            FROM outlets
            WHERE is_visible = true
              AND deactivated_at IS NULL
              AND city IS NOT NULL
              AND btrim(city) <> ''
            GROUP BY city
            ORDER BY count(*) DESC, city
        """))).fetchall()
        return [
            {"city": r.city, "outlet_count": int(r.outlet_count)}
            for r in rows
        ]

    @staticmethod
    async def list_active_cities(db: AsyncSession) -> list[dict]:
        """Cities selectable at owner signup (migration 013).

        PUBLIC and unauthenticated, because signup itself is: the dropdown has to
        populate before the owner has an account. Returns only `active` — a
        pending request is not selectable by anyone else until an admin approves
        it, otherwise one owner's typo becomes everyone's option.
        """
        rows = (await db.execute(text(
            "SELECT id, name FROM cities WHERE status = 'active' ORDER BY name"
        ))).fetchall()
        return [{"id": r.id, "name": r.name} for r in rows]
