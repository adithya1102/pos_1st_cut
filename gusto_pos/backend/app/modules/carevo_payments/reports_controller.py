"""TASK 7 — reconciliation reports + REVIEW-event disposition.

ADDITIVE. Admin routes reuse get_current_super_admin (carevo_admin/deps.py)
exactly as every other admin route in this codebase does. Owner routes
check users.is_outlet_owner directly (migration 037) and that the caller's
OWN staff.outlet_id matches the outlet_id in the path -- an owner can never
read another outlet's numbers.

Confirm/reject on a REVIEW payment_events row writes ONLY an
admin_audit_logs row (via the existing AdminService._audit, so it appears
in the existing GET /admin/audit-logs "show history" surface for free). It
deliberately does NOT retroactively flip payment_events.outcome or re-run
the original skipped effect -- that would need the SAME effect-application
logic reconciliation.apply_vendor_payment_event already has, re-entered
from a human decision instead of a webhook delivery, which is out of scope
here. See docs/runbooks/RECONCILIATION.md's known limitations.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_admin.deps import get_current_super_admin
from app.modules.carevo_admin.service import AdminService
from app.modules.carevo_customer.deps import get_current_staff
from app.modules.carevo_payments import fee_ledger as fl
from app.modules.carevo_payments import reconciliation as rec
from app.modules.carevo_payments import reports_service as rs
from app.modules.users.model import User

router = APIRouter()


# ------------------------------- admin ---------------------------------

@router.get("/admin/reports/daily")
async def admin_daily_report(
    date: str = Query(..., description="YYYY-MM-DD, IST calendar day"),
    outlet_id: Optional[uuid.UUID] = Query(None),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    if outlet_id is not None:
        return await rs.daily_report(db, outlet_id=outlet_id, date_str=date)
    return await rs.daily_report_all_outlets(db, date_str=date)


@router.get("/admin/fee-ledger/uncharged")
async def list_uncharged_completed(
    outlet_id: Optional[uuid.UUID] = Query(None),
    since: Optional[datetime] = Query(None),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """COMPLETED, payment-confirmed orders with no CHARGE row yet (Task 3,
    reconcile fix pass 2) -- a missed charge from a ledger failure, or any
    order that completed while SERVICE_FEE_LEDGER_ENABLED was off."""
    rows = await fl.find_uncharged_completed(db, outlet_id=outlet_id, since=since)
    return {"count": len(rows), "orders": rows}


@router.post("/admin/fee-ledger/charge-missing")
async def run_charge_missing(
    outlet_id: Optional[uuid.UUID] = Query(None),
    since: Optional[datetime] = Query(None),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Idempotently charge every order list_uncharged_completed finds.
    No-op while SERVICE_FEE_LEDGER_ENABLED is false, same as every other
    fee_ledger entry point."""
    return await fl.charge_missing(db, outlet_id=outlet_id, since=since)


class ReviewDecisionIn(BaseModel):
    reason: str = Field(min_length=1)


_RESOLVE_ACTIONS = ("payment_event_confirm", "payment_event_reject")


async def _load_payment_event(db: AsyncSession, event_id):
    return (await db.execute(text(
        "SELECT id, outcome FROM payment_events WHERE id = :id"),
        {"id": str(event_id)})).first()


async def _already_resolved(db: AsyncSession, event_id) -> bool:
    """A REVIEW event is resolved once EITHER confirm or reject has ever
    been recorded against it in admin_audit_logs -- there is no separate
    "resolved" column on payment_events, so this IS the resolution record,
    the same log GET /admin/audit-logs already reads."""
    row = (await db.execute(text("""
        SELECT 1 FROM admin_audit_logs
         WHERE target_type = 'payment_event' AND target_id = :id
           AND action = ANY(:actions)
         LIMIT 1
    """), {"id": str(event_id), "actions": list(_RESOLVE_ACTIONS)})).first()
    return row is not None


async def _require_resolvable_review(db: AsyncSession, event_id):
    """Loads the event and enforces: exists (404), outcome is REVIEW (409),
    and not already resolved by a prior confirm/reject (409). Writes no
    audit row on any of these -- only a genuinely new decision on a
    genuinely pending REVIEW event reaches that far."""
    row = await _load_payment_event(db, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="payment event not found")
    if row[1] != rec.OUTCOME_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"payment event outcome is {row[1]}, not REVIEW")
    if await _already_resolved(db, event_id):
        raise HTTPException(
            status_code=409, detail="payment event has already been resolved")
    return row


@router.post("/admin/payment-events/{event_id}/confirm")
async def confirm_review_event(
    event_id: uuid.UUID,
    payload: ReviewDecisionIn,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _require_resolvable_review(db, event_id)
    await AdminService._audit(
        db, admin, "payment_event_confirm", "payment_event", event_id,
        {"reason": payload.reason, "prior_outcome": row[1]})
    await db.commit()
    return {"event_id": str(event_id), "decision": "confirm", "reason": payload.reason}


@router.post("/admin/payment-events/{event_id}/reject")
async def reject_review_event(
    event_id: uuid.UUID,
    payload: ReviewDecisionIn,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _require_resolvable_review(db, event_id)
    await AdminService._audit(
        db, admin, "payment_event_reject", "payment_event", event_id,
        {"reason": payload.reason, "prior_outcome": row[1]})
    await db.commit()
    return {"event_id": str(event_id), "decision": "reject", "reason": payload.reason}


# ------------------------------- owner ----------------------------------

def _require_owner_of(staff: User, outlet_id: uuid.UUID) -> None:
    if not bool(getattr(staff, "is_outlet_owner", False)):
        raise HTTPException(status_code=403, detail="Owner access required")
    if str(staff.outlet_id) != str(outlet_id):
        raise HTTPException(status_code=403, detail="Not your outlet")


@router.get("/owner/outlets/{outlet_id}/reports/daily")
async def owner_daily_report(
    outlet_id: uuid.UUID,
    date: str = Query(..., description="YYYY-MM-DD, IST calendar day"),
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    _require_owner_of(staff, outlet_id)
    return await rs.daily_report(db, outlet_id=outlet_id, date_str=date)


@router.get("/owner/outlets/{outlet_id}/fee-ledger")
async def owner_fee_ledger(
    outlet_id: uuid.UUID,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    _require_owner_of(staff, outlet_id)
    return await rs.fee_ledger_rows(db, outlet_id)
