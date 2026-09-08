"""Local testing dashboard — every route gated by the X-Testing-Key header.

Mounted under /api/v1/testing. These endpoints are PUBLIC-REACHABLE (same host
as the customer API) but secret-protected and fail-closed (see deps). They exist
for tester operations only and touch no customer/owner behaviour.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.testing_dashboard.deps import require_testing_key
from app.modules.testing_dashboard.service import TestingService

# The dependency is applied to the whole router, so no endpoint can be added
# later that forgets the gate.
router = APIRouter(
    prefix="/testing",
    tags=["Testing Dashboard (secret-gated)"],
    dependencies=[Depends(require_testing_key)],
)


class AddTesterIn(BaseModel):
    # A tester is added by identifier — a phone (OTP) OR an email (Google-only).
    # `phone_number` is still accepted as an alias so existing callers (and the
    # phone case) keep working unchanged.
    identifier: Optional[str] = None
    phone_number: Optional[str] = None
    name: Optional[str] = None

    def resolved_identifier(self) -> str:
        return (self.identifier or self.phone_number or "").strip()


class SetLabelIn(BaseModel):
    label: Optional[str] = None  # empty/None clears the label


class RejectOrderIn(BaseModel):
    reason: Optional[str] = None


@router.get("/outlets")
async def outlets(db: AsyncSession = Depends(get_db)):
    return await TestingService.outlets_status(db)


@router.get("/orders")
async def active_orders(day: Optional[str] = None,
                        db: AsyncSession = Depends(get_db)):
    # `day` is an IST calendar date, YYYY-MM-DD; omitted means today IST. Flat
    # across all outlets, newest first — the page no longer regroups by outlet.
    return await TestingService.active_orders(db, day)


@router.get("/testers")
async def list_testers(db: AsyncSession = Depends(get_db)):
    return await TestingService.list_testers(db)


@router.post("/testers")
async def add_tester(payload: AddTesterIn, db: AsyncSession = Depends(get_db)):
    return await TestingService.add_tester(
        db, payload.resolved_identifier(), payload.name)


@router.delete("/testers/{identifier:path}")
async def remove_tester(identifier: str, db: AsyncSession = Depends(get_db)):
    # :path so a '+' (phone) or an email identifier survives routing intact.
    return await TestingService.remove_tester(db, identifier)


@router.patch("/labels/{identifier:path}")
async def set_label(identifier: str, payload: SetLabelIn,
                    db: AsyncSession = Depends(get_db)):
    # :path so a phone '+91…' or an email survives routing intact.
    return await TestingService.set_label(db, identifier, payload.label or "")


@router.post("/orders/{order_id}/approve")
async def approve_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Reuses CarevoService.advance_status (the exact staff/auto_receive action).
    return await TestingService.approve_order(db, order_id)


@router.post("/orders/{order_id}/ready")
async def ready_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Reuses CarevoService.advance_status with an explicit READY target — the
    # same call the auto-advance worker's final stage makes. A SEPARATE route
    # rather than a target parameter on /approve: approve deliberately passes NO
    # target so the server picks the next stage and cannot skip one, and giving
    # it a client-named target would remove exactly that guarantee.
    return await TestingService.ready_order(db, order_id)


@router.post("/orders/{order_id}/deliver")
async def deliver_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Reuses CarevoService.verify_pickup with the order's own pickup_code —
    # the same call auto-pickup and the owner_app counter scan both make.
    return await TestingService.deliver_order(db, order_id)


@router.post("/orders/{order_id}/reject")
async def reject_order(order_id: uuid.UUID,
                       payload: RejectOrderIn | None = None,
                       db: AsyncSession = Depends(get_db)):
    # Reuses CarevoService.reject_order (the exact owner_app Reject action).
    return await TestingService.reject_order(
        db, order_id, payload.reason if payload else None)


@router.get("/compliance")
async def compliance(db: AsyncSession = Depends(get_db)):
    return await TestingService.compliance(db)
