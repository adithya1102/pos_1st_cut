"""UNAUTHENTICATED, READ-ONLY catalogue. Mounted at /api/v1/public.

This router is open BY DESIGN, and it is the only router in this codebase for
which that is a design rather than an accident. Everything reachable here is
information a restaurant wants a stranger to find: its name, where it is, when
it opens, and what it sells. It is the same class of data a shopfront puts on
the pavement.

That design only holds because of what the schemas refuse to carry. The five
legacy routers closed earlier today were not dangerous because they were
unauthenticated — they were dangerous because they were unauthenticated AND
served whole ORM rows. `GET /outlets/` handed over phone_number,
organization_id and geofence_radius_meters with no token; the fix for that one
was a guard, and the reason this router does not need the same guard is that
its response models name every field they publish and nothing else.

So the rule for adding anything here: if a new route cannot state its exact
output fields in a hand-written model, it does not belong in this module.

NO `description` FIELD ON ITEMS. It was asked for and it is not served,
because `menu_items` has no such column — the model does not declare one, no
migration adds one, and neither the menu schema nor the customer menu endpoint
references one. The nearest things that do exist are `tags` (free-form labels
like "spicy"/"bestseller") and `short_code` (a till abbreviation), and neither
is a description. Publishing either under that name would be inventing data.

WRITES ARE STRUCTURALLY IMPOSSIBLE here: only GET routes are declared, and the
service layer issues SELECT only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.public.schema import PublicMenu, PublicOutlet
from app.modules.public.service import PublicCatalogService, check_public_rate_limit

router = APIRouter(prefix="/public", tags=["Public Catalogue"])


def _client_ip(request: Request) -> str:
    """Caller IP for the rate-limit bucket.

    Behind Render's proxy the socket peer is the proxy, so X-Forwarded-For is
    read first and its LEFTMOST entry taken (the chain appends on the way in,
    so the left end is the original client). The header is spoofable and is NOT
    used for anything but bucketing a rate limit — no authorization decision
    depends on it. Falls back to the socket peer when absent.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/outlets", response_model=list[PublicOutlet])
async def list_public_outlets(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Every publicly listed outlet: name, city, coordinates, hours, open status.

    Same visibility gate as the customer app's own list — an outlet hidden or
    deactivated there is absent here too.
    """
    check_public_rate_limit(_client_ip(request))
    return await PublicCatalogService.list_outlets(db)


@router.get("/outlets/{outlet_id}/menu", response_model=PublicMenu)
async def get_public_menu(
    outlet_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """The outlet's current menu: item name, price, veg flag, availability.

    404 for an unknown OR unlisted outlet — the two are deliberately
    indistinguishable, so this cannot be used to discover hidden outlets.
    """
    check_public_rate_limit(_client_ip(request))
    return await PublicCatalogService.get_menu(db, outlet_id)
