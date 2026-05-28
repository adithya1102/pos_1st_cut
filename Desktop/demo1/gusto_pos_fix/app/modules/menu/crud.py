"""
Menu CRUD service.

Every method that returns a MenuRead (with categories/items nested)
must eagerly load: Menu → categories → menu_items.

Never call db.refresh(menu) and expect categories to be populated —
refresh only reloads scalar columns.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Menu
from app.modules.crud_base import CRUDBase
from app.modules.menu.schemas import MenuCreate, MenuRead, MenuReadSimple, MenuUpdate


def _full_load():
    """Returns the selectinload option chain for a fully-hydrated Menu."""
    return selectinload(Menu.categories).selectinload(
        # import here to avoid circular — category is on same models file
        __import__("app.models.models", fromlist=["Category"]).Category.menu_items
    )


class MenuCRUD(CRUDBase[Menu]):

    async def create_menu(
        self, db: AsyncSession, data: MenuCreate
    ) -> MenuRead:
        """
        Create menu, then re-query with eager loads before Pydantic touches it.
        This avoids MissingGreenlet from lazy relationship access in serialization.
        """
        menu = Menu(**data.model_dump())
        db.add(menu)
        await db.commit()
        # Do NOT call db.refresh(menu) — it only loads scalars and then
        # Pydantic will attempt to access .categories which triggers lazy load → MissingGreenlet.
        # Re-query with explicit eager loading instead:
        return await self.get_with_full_load(db, menu.id)

    async def get_with_full_load(
        self, db: AsyncSession, menu_id: UUID
    ) -> MenuRead | None:
        from app.models.models import Category  # local import avoids circular
        stmt = (
            select(Menu)
            .where(Menu.id == menu_id)
            .options(
                selectinload(Menu.categories).selectinload(Category.menu_items)
            )
        )
        result = await db.execute(stmt)
        menu = result.scalar_one_or_none()
        return menu

    async def get_menus_for_outlet(
        self, db: AsyncSession, outlet_id: UUID
    ) -> list[Menu]:
        from app.models.models import Category
        stmt = (
            select(Menu)
            .where(Menu.outlet_id == outlet_id)
            .options(
                selectinload(Menu.categories).selectinload(Category.menu_items)
            )
            .order_by(Menu.created_at.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def update_menu(
        self, db: AsyncSession, menu_id: UUID, data: MenuUpdate
    ) -> MenuRead | None:
        menu = await self.get_with_full_load(db, menu_id)
        if not menu:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(menu, field, value)
        db.add(menu)
        await db.commit()
        # Re-query after commit (expire_on_commit=False keeps scalars, but safer to reload)
        return await self.get_with_full_load(db, menu_id)


menu_crud = MenuCRUD(Menu)
