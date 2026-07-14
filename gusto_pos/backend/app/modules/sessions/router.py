from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.sessions.service import SessionService

router = APIRouter(prefix="/sessions", tags=["Sessions"])


class SendOtpReq(BaseModel):
    phone: str
    table_id: Optional[str] = None
    outlet_id: Optional[str] = None


class VerifyOtpReq(BaseModel):
    phone: str
    otp: str
    table_id: str
    outlet_id: str
    customer_name: Optional[str] = ""


class WaiterActionReq(BaseModel):
    notification_id: str
    confirmed: bool
    waiter_note: Optional[str] = ""


@router.post("/send-otp")
async def send_otp(data: SendOtpReq, db: AsyncSession = Depends(get_db)):
    return await SessionService.send_otp(db, data.phone)


@router.post("/verify-otp")
async def verify_otp(data: VerifyOtpReq, db: AsyncSession = Depends(get_db)):
    return await SessionService.verify_otp(
        db, data.phone, data.otp, data.table_id, data.outlet_id, data.customer_name or ""
    )


@router.get("/status/{session_id}")
async def session_status(session_id: str, db: AsyncSession = Depends(get_db)):
    return await SessionService.get_status(db, session_id)


@router.get("/waiter/notifications/{outlet_id}")
async def get_notifications(outlet_id: str, db: AsyncSession = Depends(get_db)):
    return await SessionService.get_notifications(db, outlet_id)


@router.post("/waiter/action")
async def waiter_action(data: WaiterActionReq, db: AsyncSession = Depends(get_db)):
    return await SessionService.waiter_action(db, data.notification_id, data.confirmed)


@router.post("/custom-request")
async def custom_request(session_id: str, table_id: str, item_name: str,
                         customization: str, warned: bool = False,
                         db: AsyncSession = Depends(get_db)):
    return await SessionService.custom_request(
        db, session_id, table_id, item_name, customization, warned
    )
