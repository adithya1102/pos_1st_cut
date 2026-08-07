"""Push notification routes.

Two groups:
  * customer-authed token registration (mounted under /customer)
  * SUPER_ADMIN nudge triggers (mounted under /admin)

The nudge triggers are ENDPOINTS, not a scheduler, on purpose: this backend runs
on a Render free web service that sleeps after ~15 minutes idle, so an
in-process scheduler would fire only while the service happened to be awake.
Any external trigger — Render cron on a paid plan, a GitHub Action, cron-job.org
— can call these on a schedule. Idempotency lives in the database, so a trigger
firing twice cannot double-notify.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_admin.deps import get_current_super_admin
from app.modules.carevo_customer.deps import get_current_customer
from app.modules.customers.model import Customer
from app.modules.push import schema as s
from app.modules.push.service import PushService
from app.modules.users.model import User

customer_router = APIRouter(prefix="/customer", tags=["CareVo Skip — Customer"])
admin_router = APIRouter(prefix="/admin", tags=["CareVo Admin"])


@customer_router.post("/push/register", response_model=s.RegisterTokenOut)
async def register_push_token(
    payload: s.RegisterTokenIn,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Store this device's FCM token against the signed-in customer.

    Scoped to the bearer token — no customer id is accepted, so one customer
    cannot point another's notifications at their own device.
    """
    try:
        return await PushService.register_token(db, customer, payload.fcm_token)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@customer_router.delete("/push/register", response_model=s.RegisterTokenOut)
async def clear_push_token(
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Drop the token — called on logout so a shared device stops receiving
    pushes for an account that is no longer signed in."""
    await PushService.clear_token(db, customer)
    return {"ok": True, "push_configured": False}


@admin_router.post("/push/reengagement", response_model=s.NudgeRunOut)
async def run_reengagement(
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Nudge customers with no paid order for >14 days. Once per 30 days each.

    Safe to call repeatedly: the cooldown is enforced by a query against
    push_notifications, so a double-fire sends nothing extra.
    """
    return await PushService.run_reengagement(db)


@admin_router.post("/push/dish-suggestion", response_model=s.NudgeRunOut)
async def run_dish_suggestion(
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Nudge naming each customer's most-ordered dish and usual outlet.

    Rule-based aggregates only. Trigger this in the evening if you want evening
    delivery — the function itself does not read the clock, so it stays
    testable at any hour.
    """
    return await PushService.run_dish_suggestion(db)
