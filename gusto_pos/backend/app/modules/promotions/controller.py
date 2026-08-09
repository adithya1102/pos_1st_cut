"""Promotion routes for all three audiences (migration 016).

One module, three routers, because they share one service and splitting them
would mean three copies of the same validation:

  /admin/promotions   SUPER_ADMIN   -> scope is ALWAYS CAREVO_CAMPAIGN
  /pos/offers         staff JWT     -> scope is ALWAYS RESTAURANT_OFFER,
                                       outlet is ALWAYS the caller's own
  /customer/offers    customer JWT  -> read-only

The scope constants below are passed by the ENDPOINT, never read from a request
body. There is no field an owner could send to create a CareVo-funded campaign,
and none an admin could send to attach a campaign to an outlet they did not name.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_admin.deps import get_current_super_admin
from app.modules.carevo_admin.service import AdminService
from app.modules.carevo_customer.deps import get_current_customer, get_current_staff
from app.modules.customers.model import Customer
from app.modules.promotions import schema as s
from app.modules.promotions.service import CAMPAIGN, OFFER, PromotionService
from app.modules.users.model import User

admin_router = APIRouter(prefix="/admin/promotions", tags=["CareVo Admin — Campaigns"])
pos_router = APIRouter(prefix="/pos/offers", tags=["CareVo Skip — Restaurant Offers"])
customer_router = APIRouter(prefix="/customer", tags=["CareVo Skip — Customer"])


def _require_outlet(staff: User) -> uuid.UUID:
    """Same gate /pos/menu-items uses. An owner with no outlet has nothing to
    offer a discount on."""
    if not staff.outlet_id:
        raise HTTPException(
            status_code=403, detail="Staff account is not assigned to an outlet"
        )
    return staff.outlet_id


# ====================== CareVo Campaigns (SUPER_ADMIN) =======================
@admin_router.get("", response_model=list[s.PromotionOut])
async def list_campaigns(
    _admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Every CareVo Campaign, active first, each with its redemption count.

    Restaurant Offers are deliberately NOT listed here — they are the
    restaurants' own money and their own screen.
    """
    return await PromotionService.list_all(db, scope=CAMPAIGN)


@admin_router.post("", response_model=s.PromotionOut, status_code=201)
async def create_campaign(
    payload: s.CampaignCreateIn,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    created = await PromotionService.create(
        db, payload,
        scope=CAMPAIGN,
        created_by_user_id=admin.id,
        # NULL = platform-wide; set = targeted at one restaurant. Unlike
        # /pos/offers, an admin may legitimately name any outlet.
        outlet_id=payload.outlet_id,
    )
    await AdminService._audit(
        db, admin, action="promotion.create", target_type="promotion",
        target_id=created["id"],
        detail={
            "scope": CAMPAIGN,
            "label": payload.label,
            "code": payload.code,
            "discount_type": payload.discount_type,
            "discount_value": payload.discount_value,
            "outlet_id": str(payload.outlet_id) if payload.outlet_id else None,
            "creator_name": payload.creator_name,
            "is_active": payload.is_active,
        },
    )
    await db.commit()
    return await PromotionService.get_one(db, created["id"], scope=CAMPAIGN)


@admin_router.patch("/{promotion_id}", response_model=s.PromotionOut)
async def update_campaign(
    promotion_id: uuid.UUID,
    payload: s.CampaignUpdateIn,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Edit, and/or flip the manual on/off switch.

    Activation is a PATCH rather than a pair of dedicated endpoints because it
    is the same write; the audit trail still distinguishes the three cases so
    "who switched this on" stays answerable.
    """
    before = await PromotionService.get_one(db, promotion_id, scope=CAMPAIGN)
    await PromotionService.update(db, promotion_id, payload, scope=CAMPAIGN, outlet_id=None)

    changes = payload.model_dump(exclude_unset=True)
    toggled = "is_active" in changes and bool(changes["is_active"]) != before["is_active"]
    action = (
        ("promotion.activate" if changes["is_active"] else "promotion.deactivate")
        if toggled else "promotion.update"
    )
    await AdminService._audit(
        db, admin, action=action, target_type="promotion", target_id=promotion_id,
        detail={"label": before["label"], "changes": changes},
    )
    await db.commit()
    return await PromotionService.get_one(db, promotion_id, scope=CAMPAIGN)


# ==================== Restaurant Offers (outlet staff) =======================
@pos_router.get("", response_model=list[s.PromotionOut])
async def list_offers(
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """This outlet's own offers. Scoped by the SAME `_require_outlet(staff)`
    pattern as /pos/menu-items — there is no outlet_id parameter to tamper with,
    so an owner cannot read another restaurant's offers."""
    return await PromotionService.list_all(
        db, scope=OFFER, outlet_id=_require_outlet(staff)
    )


@pos_router.post("", response_model=s.PromotionOut, status_code=201)
async def create_offer(
    payload: s.OfferCreateIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Create an offer funded by the caller's own outlet.

    `scope=OFFER` and `outlet_id=<caller's outlet>` are hard-coded here. The
    percentage cap guardrail is enforced three times over: OfferCreateIn's
    validator, PromotionService._guardrail, and the DB CHECK
    `promotions_percent_offer_requires_cap`.
    """
    outlet_id = _require_outlet(staff)
    created = await PromotionService.create(
        db, payload, scope=OFFER, created_by_user_id=staff.id, outlet_id=outlet_id
    )
    await db.commit()
    return await PromotionService.get_one(db, created["id"], scope=OFFER, outlet_id=outlet_id)


@pos_router.patch("/{promotion_id}", response_model=s.PromotionOut)
async def update_offer(
    promotion_id: uuid.UUID,
    payload: s.OfferUpdateIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Edit or toggle. The outlet filter is part of the lookup, so patching an
    id belonging to another restaurant is a 404, not a silent cross-outlet write."""
    outlet_id = _require_outlet(staff)
    await PromotionService.update(db, promotion_id, payload, scope=OFFER, outlet_id=outlet_id)
    await db.commit()
    return await PromotionService.get_one(db, promotion_id, scope=OFFER, outlet_id=outlet_id)


# =========================== Customer-facing read ============================
@customer_router.get("/offers", response_model=list[s.CustomerOfferOut])
async def list_customer_offers(
    outlet_id: uuid.UUID = Query(..., description="Restaurant being browsed"),
    _customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Active CareVo Campaigns (platform-wide + targeted at this outlet) UNION
    this outlet's active Restaurant Offers, as one list.

    Funding is not surfaced as a filter — `scope` rides along only so the app
    can badge a CareVo campaign differently from the restaurant's own offer.
    """
    return await PromotionService.list_for_customer(db, outlet_id)
