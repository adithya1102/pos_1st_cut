import random
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager, waiter_manager
from app.modules.orders.service import fire
from app.modules.sessions.models import CustomerSession, OtpRecord, WaiterNotification


class SessionService:
    @staticmethod
    async def send_otp(db: AsyncSession, phone: str) -> dict:
        otp = str(random.randint(100000, 999999))
        db.add(OtpRecord(phone=phone, otp=otp))
        await db.commit()
        print(f"[DEV OTP] {phone} -> {otp}")
        return {"message": "OTP sent", "dev_otp": otp}

    @staticmethod
    async def _active_session(db: AsyncSession, customer_id: str, table_id: str, outlet_id: str):
        r = await db.execute(
            select(CustomerSession).where(
                CustomerSession.customer_id == customer_id,
                CustomerSession.table_id == table_id,
                CustomerSession.outlet_id == uuid.UUID(outlet_id),
                CustomerSession.is_active == True,
                CustomerSession.expires_at > datetime.utcnow(),
            ).order_by(CustomerSession.created_at.desc())
        )
        return r.scalar_one_or_none()

    @staticmethod
    async def verify_otp(db: AsyncSession, phone: str, otp: str, table_id: str,
                         outlet_id: str, customer_name: str = "") -> dict:
        res = await db.execute(
            select(OtpRecord).where(
                OtpRecord.phone == phone,
                OtpRecord.otp == otp,
                OtpRecord.used == False,
            ).order_by(OtpRecord.created_at.desc())
        )
        rec = res.scalar_one_or_none()
        if not rec:
            raise HTTPException(400, "Invalid or expired OTP")
        rec.used = True

        existing = await SessionService._active_session(db, phone, table_id, outlet_id)
        if existing and existing.confirmed_by_waiter:
            await db.commit()
            return {"session_id": str(existing.id), "confirmed": True, "message": "Welcome back!"}

        name = customer_name or phone
        s = CustomerSession(
            outlet_id=uuid.UUID(outlet_id),
            table_id=table_id,
            customer_id=phone,
            login_type="phone",
            customer_name=name,
            expires_at=datetime.utcnow() + timedelta(hours=5),
        )
        db.add(s)
        await db.flush()
        db.add(WaiterNotification(
            outlet_id=uuid.UUID(outlet_id),
            table_id=table_id,
            customer_name=name,
            customer_id=phone,
            notif_type="confirm_session",
            session_id=s.id,
        ))
        await db.commit()

        # A customer is sitting down and waiting to be approved — alert the floor
        session_event = {
            "type": "session_request",
            "session_id": str(s.id),
            "table_id": table_id,
            "customer_name": name,
        }
        fire(manager.notify_waiters(outlet_id, session_event))
        fire(waiter_manager.broadcast_order_event(
            outlet_id, "SESSION_REQUEST",
            {"session_id": str(s.id), "table_id": table_id, "customer_name": name},
        ))

        return {"session_id": str(s.id), "confirmed": False, "message": "Waiting for waiter"}

    @staticmethod
    async def get_status(db: AsyncSession, session_id: str) -> dict:
        res = await db.execute(
            select(CustomerSession).where(CustomerSession.id == uuid.UUID(session_id))
        )
        s = res.scalar_one_or_none()
        if not s:
            return {"confirmed": False, "expired": True}
        return {
            "confirmed": s.confirmed_by_waiter,
            "expired": datetime.utcnow() > s.expires_at,
            "table_id": s.table_id,
            "customer_name": s.customer_name,
        }

    @staticmethod
    async def get_notifications(db: AsyncSession, outlet_id: str) -> list[dict]:
        res = await db.execute(
            select(WaiterNotification).where(
                WaiterNotification.outlet_id == uuid.UUID(outlet_id),
                WaiterNotification.is_read == False,
            ).order_by(WaiterNotification.created_at.desc())
        )
        return [
            {
                "id": str(n.id),
                "table_id": n.table_id,
                "customer_name": n.customer_name,
                "type": n.notif_type,
                "order_preview": n.order_preview,
                "session_id": str(n.session_id) if n.session_id else None,
                "order_id": str(n.order_id) if n.order_id else None,
                "total_amount": float(n.total_amount) if n.total_amount is not None else None,
                "is_read": n.is_read,
                "is_confirmed": n.is_confirmed,
                "created_at": str(n.created_at),
            }
            for n in res.scalars().all()
        ]

    @staticmethod
    async def waiter_action(db: AsyncSession, notification_id: str, confirmed: bool) -> dict:
        res = await db.execute(
            select(WaiterNotification).where(WaiterNotification.id == uuid.UUID(notification_id))
        )
        n = res.scalar_one_or_none()
        if not n:
            raise HTTPException(404, "Not found")
        n.is_read = True
        n.is_confirmed = confirmed

        if n.session_id:
            sr = await db.execute(
                select(CustomerSession).where(CustomerSession.id == n.session_id)
            )
            s = sr.scalar_one_or_none()
            if s:
                s.confirmed_by_waiter = confirmed
                s.is_active = confirmed
        await db.commit()

        if n.table_id:
            fire(manager.notify_customer(n.table_id, {
                "type": "session_confirmed" if confirmed else "session_rejected",
                "message": "Welcome! You can start ordering." if confirmed
                           else "Please ask your waiter for assistance.",
            }))
        return {"message": "Done"}

    @staticmethod
    async def custom_request(db: AsyncSession, session_id: str, table_id: str, item_name: str,
                             customization: str, warned: bool = False) -> dict:
        res = await db.execute(
            select(CustomerSession).where(CustomerSession.id == uuid.UUID(session_id))
        )
        s = res.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Session not found")
        preview = f"{item_name}: {customization}" + (" [WAITER WARNED]" if warned else "")
        db.add(WaiterNotification(
            outlet_id=s.outlet_id,
            table_id=table_id,
            customer_name=s.customer_name,
            customer_id=s.customer_id,
            notif_type="custom_order",
            order_preview=preview,
            session_id=s.id,
        ))
        await db.commit()

        fire(manager.notify_waiters(str(s.outlet_id), {
            "type": "custom_request",
            "table_id": table_id,
            "customer_name": s.customer_name,
            "preview": preview,
        }))
        return {"message": "Waiter notified"}
