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


@router.post("/outlets/{outlet_id}/deactivate", response_model=s.OutletDeactivateOut)
async def deactivate_outlet(
    outlet_id: uuid.UUID,
    payload: s.OutletDecisionIn | None = None,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (deactivate). Hides the outlet from customers + forces
    is_visible=false; retains all order/event history. Reversible."""
    return await AdminService.deactivate_outlet(
        db, admin, outlet_id, payload.reason if payload else None
    )


@router.post("/outlets/{outlet_id}/reactivate", response_model=s.OutletDeactivateOut)
async def reactivate_outlet(
    outlet_id: uuid.UUID,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.reactivate_outlet(db, admin, outlet_id)


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


# --------------------------- customer directory ----------------------------
@router.get("/customers", response_model=list[s.CustomerDirectoryOut])
async def list_customers(
    limit: int = Query(200, ge=1, le=1000),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.list_customers(db, limit=limit)


# ------------------------------ orders -------------------------------------
@router.get("/orders", response_model=s.AdminOrderPageOut)
async def list_orders(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Every order across every outlet, newest first.

    Paginated rather than capped. The customer directory takes a bare `limit`
    and silently drops everything past it — tolerable for a directory, not for
    an order log that grows with each sale, so this returns `total` and an
    `offset` the caller can page with.

    Deliberately GET-only and separate from /admin/customers: this is an order
    log, and the customer directory's columns are left exactly as they were.
    """
    return await AdminService.list_orders(db, limit=limit, offset=offset)


@router.get("/orders/by-restaurant", response_model=s.RestaurantTabOut)
async def list_orders_by_restaurant(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(2000, ge=1, le=5000),
    outlet_id: Optional[uuid.UUID] = Query(None),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Orders grouped restaurant -> day -> time, for the Restaurant tab.

    A different VIEW of the same rows /admin/orders returns — no new table and
    no new column. Same SUPER_ADMIN gate as every other route in this module.

    Windowed (`days`) rather than paginated: paging a tree can split one
    restaurant's days across two pages, producing a group that looks complete
    and is not. `limit` remains a safety cap, but the response now reports
    `truncated` when it bites, so a short tree is never mistaken for a complete
    one. `outlet_id` scopes to a single restaurant.
    """
    return await AdminService.list_orders_by_restaurant(
        db, days=days, limit=limit, outlet_id=outlet_id
    )


# ------------------------------ cities -------------------------------------
# Same shape as the outlet verification queue above, deliberately: pending rows
# listed, then approve/reject, each writing an admin_audit_logs entry.
@router.get("/cities", response_model=list[s.AdminCityOut])
async def list_cities(
    status: Optional[str] = Query(None),
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.list_cities(db, status)


@router.post("/cities/{city_id}/approve", response_model=s.CityDecisionOut)
async def approve_city(
    city_id: uuid.UUID,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Make a requested city selectable for future signups."""
    return await AdminService.decide_city(db, admin, city_id, "active")


@router.post("/cities/{city_id}/reject", response_model=s.CityDecisionOut)
async def reject_city(
    city_id: uuid.UUID,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService.decide_city(db, admin, city_id, "rejected")


@router.post("/cities", response_model=s.CityCreateOut, status_code=201)
async def create_city(
    payload: s.CityCreateIn,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add a city that is immediately selectable.

    SUPER_ADMIN only, and deliberately a separate route from the public
    `/register` rather than a bypass flag on it: `/register` is
    unauthenticated, so a "skip the pending gate" parameter there would be an
    open privilege escalation. owner_app's `requested_city` path is untouched
    and still lands as 'pending'.
    """
    return await AdminService.create_active_city(db, admin, payload.name)


@router.patch("/cities/{city_id}", response_model=s.CityRenameOut)
async def rename_city(
    city_id: uuid.UUID,
    payload: s.CityRenameIn,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Rename in place, carrying every outlet that holds the old spelling.

    409 on a case-insensitive collision with a different city: that would be a
    merge, not a rename, and merges do not happen as a side effect of an edit.
    """
    return await AdminService.rename_city(db, admin, city_id, payload.name)


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
