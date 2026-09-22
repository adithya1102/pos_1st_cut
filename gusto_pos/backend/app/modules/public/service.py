"""Read-only queries behind /public/*.

Raw SQL with an EXPLICIT column list, never `SELECT *` and never an ORM row
handed to a response model. Two reasons, and the second is the important one:

  1. Several of the columns involved (opens_at, closes_at, is_manually_closed,
     is_available, is_visible, deactivated_at) were added by migrations and do
     not exist on the SQLAlchemy models at all — the ORM cannot see them.

  2. Naming every column means a new column in `outlets` or `menu_items` is
     invisible here by default. With `SELECT *` feeding a permissive model, the
     next migration decides what this public endpoint publishes.
"""

from __future__ import annotations

import time as _time
import uuid
from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.carevo_customer.service import CarevoService

# --- Per-IP rate limiter ----------------------------------------------------
# Same shape as _otp_hits / _register_hits in carevo_customer/service.py, and
# the same caveat applies verbatim: SINGLE-PROCESS. It counts requests seen by
# one worker, so N workers permit roughly N times the limit, and a restart
# forgets everything. Redis in prod if this ever needs to be exact.
#
# Reused rather than reinvented on purpose — the mechanism the codebase already
# has, with its known limits, beats a second mechanism with different ones.
_public_hits: dict[str, list[float]] = defaultdict(list)


def check_public_rate_limit(client_ip: str) -> None:
    """Per-IP cap, mirroring CarevoService.check_register_rate_limit."""
    now = _time.time()
    window = 3600.0
    hits = [t for t in _public_hits[client_ip] if now - t < window]
    if len(hits) >= settings.PUBLIC_API_RATE_LIMIT_PER_HOUR:
        _public_hits[client_ip] = hits
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests, try later",
            headers={"Retry-After": "3600"},
        )
    hits.append(now)
    _public_hits[client_ip] = hits


class PublicCatalogService:
    # Visibility gate, IDENTICAL to the one CarevoService.list_outlets uses.
    # An outlet hidden from the customer app must not be discoverable here
    # instead — two different definitions of "listed" is how a deactivated
    # restaurant keeps taking traffic through the back door.
    _VISIBLE = "is_visible = true AND deactivated_at IS NULL"

    @staticmethod
    async def list_outlets(db: AsyncSession) -> list[dict]:
        rows = (await db.execute(text(f"""
            SELECT id, location_name, city, latitude, longitude,
                   opens_at, closes_at, is_manually_closed
            FROM outlets
            WHERE {PublicCatalogService._VISIBLE}
            ORDER BY city NULLS LAST, location_name
        """))).fetchall()

        out: list[dict] = []
        for r in rows:
            avail = CarevoService.outlet_availability(
                r.opens_at, r.closes_at, r.is_manually_closed
            )
            out.append({
                "id": r.id,
                "name": r.location_name,
                "city": r.city,
                # DECIMAL -> float. None stays None.
                "latitude": float(r.latitude) if r.latitude is not None else None,
                "longitude": float(r.longitude) if r.longitude is not None else None,
                "opens_at": r.opens_at,
                "closes_at": r.closes_at,
                "open_status": avail["status"],
                "open_reason": avail["reason"],
            })
        return out

    @staticmethod
    async def get_menu(db: AsyncSession, outlet_id: uuid.UUID) -> dict:
        # Resolve the outlet through the SAME visibility gate as the list. A
        # hidden outlet's menu 404s rather than 403s: "no such public outlet"
        # is the honest answer, and distinguishing "exists but hidden" from
        # "does not exist" would leak the existence of unlisted restaurants.
        outlet = (await db.execute(text(f"""
            SELECT id, location_name FROM outlets
            WHERE id = :oid AND {PublicCatalogService._VISIBLE}
        """), {"oid": str(outlet_id)})).first()
        if not outlet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Outlet not found"
            )

        # is_active filters (deleted items should not exist for a reader);
        # is_available does NOT filter, it is published — same rule as the
        # customer menu, so the two cannot disagree about what is on offer.
        # c.id is selected only to group by — a category whose name collides
        # with another's would otherwise silently merge two sections into one.
        # It is NOT published; see PublicMenuCategory.
        #
        # Inner JOIN, not LEFT: a category with no active items is dropped
        # rather than served as an empty section. The customer app's own menu
        # uses LEFT because its UI renders section headers from the category
        # list; a public reader asking what is on offer gains nothing from a
        # heading with nothing under it.
        rows = (await db.execute(text("""
            SELECT c.id AS cat_id, c.name AS cat_name,
                   mi.name, mi.base_price, mi.is_veg, mi.is_available
            FROM categories c
            JOIN menus m ON m.id = c.menu_id
            JOIN menu_items mi
              ON mi.category_id = c.id AND mi.is_active = true
            WHERE m.outlet_id = :oid AND m.is_latest = true
            ORDER BY c.name, mi.name
        """), {"oid": str(outlet_id)})).fetchall()

        # Insertion-ordered: the query sorts by category name then item name,
        # so building in row order preserves that without a second sort.
        categories: dict[str, dict] = {}
        for r in rows:
            key = str(r.cat_id)
            if key not in categories:
                categories[key] = {"name": r.cat_name, "items": []}
            categories[key]["items"].append({
                "name": r.name,
                "price": float(r.base_price),
                "is_veg": bool(r.is_veg),
                "is_available": bool(r.is_available),
            })

        return {
            "outlet_id": outlet.id,
            "outlet_name": outlet.location_name,
            "categories": list(categories.values()),
        }
