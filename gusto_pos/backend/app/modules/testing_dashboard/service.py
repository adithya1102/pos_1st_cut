"""Queries + window/roster logic for the local testing dashboard.

Roster (migration 025) is the single source of truth for BOTH auto-pickup scope
and the compliance list. Nothing here is customer-facing; all of it sits behind
the X-Testing-Key gate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.carevo_customer.service import CarevoService

# The compliance day runs 23:00 -> 23:00 in India. Every outlet, customer, and
# the operating-hours gate (migration 024) already reason in IST, so the day
# boundary is IST too — a UTC boundary would roll over at 04:30/05:30 local,
# splitting an evening's testing across two "days".
TESTING_TZ = ZoneInfo("Asia/Kolkata")
WINDOW_BOUNDARY_HOUR = 23


def current_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The rolling [23:00 IST, next 23:00 IST) window that contains `now`.

    Returned in UTC, to compare against customer_orders.created_at (stored as
    timestamptz). Clock-injectable so the day-boundary maths is testable.
    """
    now = now or datetime.now(TESTING_TZ)
    ist = now.astimezone(TESTING_TZ)
    boundary = ist.replace(hour=WINDOW_BOUNDARY_HOUR, minute=0, second=0,
                           microsecond=0)
    # At/after 23:00 the new window has already started; before it, we are still
    # inside the window that began at yesterday's 23:00.
    start = boundary if ist >= boundary else boundary - timedelta(days=1)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


class TestingService:
    # ------------------------------ roster --------------------------------
    @staticmethod
    def _norm(phone: str) -> str:
        return (phone or "").strip()

    @staticmethod
    async def is_roster_phone(db: AsyncSession, phone: str | None) -> bool:
        if not phone:
            return False
        return (await db.execute(text(
            "SELECT 1 FROM testers WHERE phone_number = :p LIMIT 1"
        ), {"p": TestingService._norm(phone)})).first() is not None

    @staticmethod
    async def list_testers(db: AsyncSession) -> list[dict]:
        rows = (await db.execute(text(
            "SELECT phone_number, name, added_at FROM testers "
            "ORDER BY added_at DESC"
        ))).fetchall()
        return [{"phone_number": r.phone_number, "name": r.name,
                 "added_at": r.added_at} for r in rows]

    @staticmethod
    async def add_tester(db: AsyncSession, phone: str, name: str | None) -> dict:
        p = TestingService._norm(phone)
        if not p:
            raise HTTPException(status_code=422, detail="phone_number required")
        # Idempotent: re-adding an existing number just updates the label.
        await db.execute(text("""
            INSERT INTO testers (phone_number, name)
            VALUES (:p, :n)
            ON CONFLICT (phone_number)
            DO UPDATE SET name = COALESCE(EXCLUDED.name, testers.name)
        """), {"p": p, "n": (name or "").strip() or None})
        await db.commit()
        row = (await db.execute(text(
            "SELECT phone_number, name, added_at FROM testers WHERE phone_number = :p"
        ), {"p": p})).first()
        return {"phone_number": row.phone_number, "name": row.name,
                "added_at": row.added_at}

    @staticmethod
    async def remove_tester(db: AsyncSession, phone: str) -> dict:
        p = TestingService._norm(phone)
        res = await db.execute(text(
            "DELETE FROM testers WHERE phone_number = :p"), {"p": p})
        await db.commit()
        return {"removed": res.rowcount or 0, "phone_number": p}

    # ------------------------------ outlets -------------------------------
    @staticmethod
    async def outlets_status(db: AsyncSession) -> list[dict]:
        rows = (await db.execute(text(
            "SELECT id, location_name, city, is_visible, deactivated_at, "
            "       opens_at, closes_at, is_manually_closed "
            "FROM outlets ORDER BY location_name"
        ))).fetchall()
        out = []
        for r in rows:
            avail = CarevoService.outlet_availability(
                r.opens_at, r.closes_at, bool(r.is_manually_closed))
            out.append({
                "id": r.id,
                "name": r.location_name,
                "city": r.city,
                "is_visible": bool(r.is_visible),
                "is_deactivated": r.deactivated_at is not None,
                "opening_time": r.opens_at.strftime("%H:%M") if r.opens_at else None,
                "closing_time": r.closes_at.strftime("%H:%M") if r.closes_at else None,
                "is_manually_closed": bool(r.is_manually_closed),
                "order_status": avail["status"],
            })
        return out

    # --------------------------- active orders ----------------------------
    @staticmethod
    async def active_orders(db: AsyncSession) -> list[dict]:
        """Every non-terminal order across ALL outlets, with OTP + phone.

        Not scoped to one outlet (unlike list_active_orders) and includes the
        customer phone — this is a tester's-eye view, so it deliberately shows
        what the customer-facing and owner-facing APIs never would.
        """
        rows = (await db.execute(text("""
            SELECT co.id, co.status, co.payment_status, co.pickup_code,
                   co.total_amount, co.created_at,
                   o.location_name AS outlet_name,
                   c.phone_number  AS customer_phone,
                   c.name          AS customer_name
            FROM customer_orders co
            LEFT JOIN outlets   o ON o.id = co.outlet_id
            LEFT JOIN customers c ON c.id = co.customer_id
            WHERE co.status NOT IN ('COMPLETED','CANCELLED','ABANDONED')
            ORDER BY co.created_at DESC
        """))).fetchall()
        if not rows:
            return []
        ids = [str(r.id) for r in rows]
        items = (await db.execute(text(
            "SELECT customer_order_id, name_snap, quantity "
            "FROM customer_order_items WHERE customer_order_id = ANY(:ids) "
            "ORDER BY created_at"
        ), {"ids": ids})).fetchall()
        by_order: dict = {}
        for it in items:
            by_order.setdefault(str(it.customer_order_id), []).append(
                {"name": it.name_snap, "quantity": it.quantity})
        return [{
            "order_id": r.id,
            "outlet_name": r.outlet_name,
            "status": r.status,
            "payment_status": r.payment_status,
            "pickup_code": r.pickup_code,
            "total_amount": float(r.total_amount) if r.total_amount is not None else 0.0,
            "customer_phone": r.customer_phone,
            "customer_name": r.customer_name,
            "created_at": r.created_at,
            "items": by_order.get(str(r.id), []),
        } for r in rows]

    # ---------------------------- compliance ------------------------------
    @staticmethod
    async def compliance(db: AsyncSession, now: datetime | None = None) -> dict:
        """For each tester, whether they placed >= 1 order in the current
        rolling 23:00-IST window. 'Placed' = an order row was created, whatever
        its payment/status."""
        start_utc, end_utc = current_window(now)
        rows = (await db.execute(text("""
            SELECT t.phone_number, t.name,
                   COUNT(co.id) AS order_count
            FROM testers t
            LEFT JOIN customers c ON c.phone_number = t.phone_number
            LEFT JOIN customer_orders co
                   ON co.customer_id = c.id
                  AND co.created_at >= :start
                  AND co.created_at <  :end
            GROUP BY t.phone_number, t.name
            ORDER BY t.name NULLS LAST, t.phone_number
        """), {"start": start_utc, "end": end_utc})).fetchall()
        testers = [{
            "phone_number": r.phone_number,
            "name": r.name,
            "order_count": int(r.order_count or 0),
            "ordered": (r.order_count or 0) > 0,
        } for r in rows]
        return {
            "window_start_utc": start_utc,
            "window_end_utc": end_utc,
            "ordered": [t for t in testers if t["ordered"]],
            "not_ordered": [t for t in testers if not t["ordered"]],
        }

    # --------------------------- auto-pickup ------------------------------
    @staticmethod
    async def maybe_auto_pickup(db: AsyncSession, order) -> bool:
        """If `order` is READY and its customer's phone is on the roster,
        complete it by invoking the SAME internal verify_pickup the staff
        endpoint uses — reused verbatim, never reimplemented. Returns True if
        auto-pickup fired. Best-effort: any failure is swallowed so it can never
        affect the status transition that triggered it.

        Non-roster orders are untouched: the roster check gates everything.
        """
        try:
            if (order.status or "").upper() != "READY":
                return False
            if not order.pickup_code:
                return False
            phone = (await db.execute(text(
                "SELECT phone_number FROM customers WHERE id = :cid"
            ), {"cid": str(order.customer_id)})).scalar()
            if not await TestingService.is_roster_phone(db, phone):
                return False
            # The exact staff pickup logic, with the order's OWN code.
            await CarevoService.verify_pickup(
                db, order.id, order.pickup_code, order.outlet_id)
            return True
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            return False
