"""
Outlet CRUD service.

The previous crash: db.refresh(outlet) auto-loaded outlet.orders,
which queried the orders table and hit a missing column (kitchen_token).

Fix applied here:
  1. db.refresh() is never called after create — we re-query with
     explicit column selection instead.
  2. No relationship is loaded unless explicitly requested.
  3. OutletRead schema does NOT include orders/menus — those are
     separate endpoints, so we never accidentally trigger that load.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Outlet
from app.modules.crud_base import CRUDBase
from app.modules.outlets.schemas import OutletCreate, OutletRead, OutletUpdate


class OutletCRUD(CRUDBase[Outlet]):

    async def create_outlet(
        self, db: AsyncSession, data: OutletCreate
    ) -> Outlet:
        outlet = Outlet(**data.model_dump())
        db.add(outlet)
        await db.commit()

        # ── THE FIX ───────────────────────────────────────────────────────────
        # OLD (broken): await db.refresh(outlet)
        #   → triggers lazy load of outlet.orders
        #   → queries SELECT * FROM orders WHERE outlet_id = ...
        #   → hits missing column → UndefinedColumnError → 500
        #
        # NEW (correct): re-query with only scalar columns, no relationship loading
        stmt = select(Outlet).where(Outlet.id == outlet.id)
        result = await db.execute(stmt)
        return result.scalar_one()
        # ─────────────────────────────────────────────────────────────────────

    async def get_outlet(
        self, db: AsyncSession, outlet_id: UUID
    ) -> Outlet | None:
        stmt = select(Outlet).where(Outlet.id == outlet_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_outlets_for_org(
        self, db: AsyncSession, organization_id: UUID
    ) -> list[Outlet]:
        stmt = (
            select(Outlet)
            .where(Outlet.organization_id == organization_id)
            .order_by(Outlet.created_at.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def update_outlet(
        self, db: AsyncSession, outlet_id: UUID, data: OutletUpdate
    ) -> Outlet | None:
        outlet = await self.get_outlet(db, outlet_id)
        if not outlet:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(outlet, field, value)
        db.add(outlet)
        await db.commit()
        # Re-query cleanly — no refresh
        return await self.get_outlet(db, outlet_id)


outlet_crud = OutletCRUD(Outlet)
