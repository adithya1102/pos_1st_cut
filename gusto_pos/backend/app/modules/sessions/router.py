import uuid, random
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.modules.sessions.models import CustomerSession, OtpRecord, WaiterNotification

router = APIRouter(prefix="/sessions", tags=["Sessions"])

class SendOtpReq(BaseModel):
    phone: str

class VerifyOtpReq(BaseModel):
    phone: str; otp: str; table_id: str; outlet_id: str; customer_name: Optional[str] = ""

class WaiterActionReq(BaseModel):
    notification_id: str; confirmed: bool; waiter_note: Optional[str] = ""

@router.post("/send-otp")
async def send_otp(data: SendOtpReq, db: AsyncSession = Depends(get_db)):
    otp = str(random.randint(100000, 999999))
    db.add(OtpRecord(phone=data.phone, otp=otp))
    await db.commit()
    print(f"[DEV OTP] {data.phone} → {otp}")
    return {"message": "OTP sent", "dev_otp": otp}

@router.post("/verify-otp")
async def verify_otp(data: VerifyOtpReq, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(OtpRecord).where(
        OtpRecord.phone==data.phone, OtpRecord.otp==data.otp, OtpRecord.used==False
    ).order_by(OtpRecord.created_at.desc()))
    rec = res.scalar_one_or_none()
    if not rec: raise HTTPException(400, "Invalid or expired OTP")
    rec.used = True

    existing = await _active_session(data.phone, data.table_id, data.outlet_id, db)
    if existing and existing.confirmed_by_waiter:
        await db.commit()
        return {"session_id": str(existing.id), "confirmed": True, "message": "Welcome back!"}

    s = CustomerSession(outlet_id=uuid.UUID(data.outlet_id), table_id=data.table_id,
        customer_id=data.phone, login_type="phone",
        customer_name=data.customer_name or data.phone,
        expires_at=datetime.utcnow()+timedelta(hours=5))
    db.add(s); await db.flush()
    db.add(WaiterNotification(outlet_id=uuid.UUID(data.outlet_id), table_id=data.table_id,
        customer_name=data.customer_name or data.phone, customer_id=data.phone,
        notif_type="confirm_session", session_id=s.id))
    await db.commit()
    return {"session_id": str(s.id), "confirmed": False, "message": "Waiting for waiter"}

@router.get("/status/{session_id}")
async def session_status(session_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(CustomerSession).where(
        CustomerSession.id==uuid.UUID(session_id)))
    s = res.scalar_one_or_none()
    if not s: return {"confirmed": False, "expired": True}
    return {"confirmed": s.confirmed_by_waiter, "expired": datetime.utcnow()>s.expires_at,
            "table_id": s.table_id, "customer_name": s.customer_name}

@router.get("/waiter/notifications/{outlet_id}")
async def get_notifications(outlet_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(WaiterNotification).where(
        WaiterNotification.outlet_id==uuid.UUID(outlet_id),
        WaiterNotification.is_read==False
    ).order_by(WaiterNotification.created_at.desc()))
    return [{"id":str(n.id),"table_id":n.table_id,"customer_name":n.customer_name,
             "type":n.notif_type,"order_preview":n.order_preview,
             "session_id":str(n.session_id),"created_at":str(n.created_at)}
            for n in res.scalars().all()]

@router.post("/waiter/action")
async def waiter_action(data: WaiterActionReq, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(WaiterNotification).where(
        WaiterNotification.id==uuid.UUID(data.notification_id)))
    n = res.scalar_one_or_none()
    if not n: raise HTTPException(404, "Not found")
    n.is_read = True; n.is_confirmed = data.confirmed
    if n.session_id:
        sr = await db.execute(select(CustomerSession).where(
            CustomerSession.id==n.session_id))
        s = sr.scalar_one_or_none()
        if s: s.confirmed_by_waiter = data.confirmed; s.is_active = data.confirmed
    await db.commit()
    return {"message": "Done"}

@router.post("/custom-request")
async def custom_request(session_id: str, table_id: str, item_name: str,
                          customization: str, warned: bool = False,
                          db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(CustomerSession).where(
        CustomerSession.id==uuid.UUID(session_id)))
    s = res.scalar_one_or_none()
    if not s: raise HTTPException(404, "Session not found")
    db.add(WaiterNotification(outlet_id=s.outlet_id, table_id=table_id,
        customer_name=s.customer_name, customer_id=s.customer_id,
        notif_type="custom_order",
        order_preview=f"{item_name}: {customization}" + (" [WAITER WARNED]" if warned else ""),
        session_id=s.id))
    await db.commit()
    return {"message": "Waiter notified"}

async def _active_session(customer_id, table_id, outlet_id, db):
    r = await db.execute(select(CustomerSession).where(
        CustomerSession.customer_id==customer_id, CustomerSession.table_id==table_id,
        CustomerSession.outlet_id==uuid.UUID(outlet_id), CustomerSession.is_active==True,
        CustomerSession.expires_at>datetime.utcnow()
    ).order_by(CustomerSession.created_at.desc()))
    return r.scalar_one_or_none()
