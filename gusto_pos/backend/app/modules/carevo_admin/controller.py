"""CareVo Admin Dashboard routes. Mounted under /api/v1 -> /api/v1/admin/*.

EVERY route here is gated by get_current_super_admin (staff JWT + SUPER_ADMIN
role). Unlike /pos/*, these routes are intentionally cross-outlet: a super admin
sees and acts on all outlets, so there is no _require_outlet scoping.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_admin import schema as s
from app.modules.carevo_admin.deps import get_current_super_admin
from app.modules.carevo_admin.service import AdminService, PENDING
from app.modules.users.model import User

router = APIRouter(prefix="/admin", tags=["CareVo Admin — Platform"])


@router.get("/me", response_model=s.AdminMeOut)
async def whoami(admin: User = Depends(get_current_super_admin)):
    """Cheap token+role probe — the dashboard calls this right after login."""
    return {
        "user_id": admin.id,
        "username": admin.username,
        "is_super_admin": True,
        "roles": [r.name for r in (admin.roles or [])],
    }


# ------------------------------- outlets -----------------------------------
@router.get("/outlets", response_model=list[s.AdminOutletOut])
async def list_outlets(
    status: Optional[s.VerificationStatus] = Query(
        default=None, description="Filter by verification_status"
    ),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.list_outlets(db, status)


@router.get("/outlets/pending", response_model=list[s.AdminOutletOut])
async def list_pending_outlets(
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """The approval queue. Sugar over /admin/outlets?status=pending_verification."""
    return await AdminService.list_outlets(db, PENDING)


@router.post("/outlets/{outlet_id}/approve", response_model=s.OutletDecisionOut)
async def approve_outlet(
    outlet_id: uuid.UUID,
    payload: s.OutletDecisionIn | None = None,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.approve_outlet(
        db, admin, outlet_id, payload.reason if payload else None
    )


@router.post("/outlets/{outlet_id}/reject", response_model=s.OutletDecisionOut)
async def reject_outlet(
    outlet_id: uuid.UUID,
    payload: s.OutletDecisionIn | None = None,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.reject_outlet(
        db, admin, outlet_id, payload.reason if payload else None
    )


# ---------------------------- locked orders --------------------------------
@router.get("/orders/locked", response_model=list[s.LockedOrderOut])
async def list_locked_orders(
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.list_locked_orders(db)


@router.post("/orders/{order_id}/unlock", response_model=s.UnlockOrderOut)
async def unlock_order(
    order_id: uuid.UUID,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.unlock_order(db, admin, order_id)


# -------------------- prediction engine (shadow mode) ----------------------
# Read-only observability over migration 006's PE tables. No response_model:
# the payloads are nested and mix UUID/datetime/Decimal/JSONB, which FastAPI's
# jsonable_encoder serialises cleanly without a hand-maintained schema.
@router.get("/prediction/overview")
async def prediction_overview(
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """FR-A3 shadow-mode status + FR-A4 global data health toward graduation."""
    return await AdminService.prediction_overview(db)


@router.get("/prediction/outlets")
async def prediction_outlets(
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """FR-A2 per-outlet prediction quality (trust, calibration, tap discipline)."""
    return await AdminService.prediction_outlets(db)


@router.get("/prediction/orders")
async def prediction_recent_orders(
    limit: int = Query(default=50, ge=1, le=200),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Recent orders with an event stream — the drill-in list for timelines."""
    return await AdminService.prediction_recent_orders(db, limit)


@router.get("/prediction/orders/{order_id}/timeline")
async def order_timeline(
    order_id: uuid.UUID,
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """FR-A1 per-order event timeline + twin promise + predictions + outcome."""
    return await AdminService.order_timeline(db, order_id)


# ------------------------------ audit log ----------------------------------
@router.get("/audit-logs", response_model=list[s.AuditLogOut])
async def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.list_audit_logs(db, limit)
