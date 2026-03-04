"""Service layer for Menu operations.

FIX: Removed selectinload(Menu.outlet) and selectinload(MenuCategory.menu)
from all queries. Schemas only need outlet_id / menu_id (scalar FK columns),
NOT the full relationship object. Loading the Outlet relationship cascades
via lazy="selectin" into orders/staff/tables which hits missing DB columns.
"""
from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.menu.model import Menu, MenuCategory, MenuItem, ItemModifier
from app.modules.menu.schema import (
    MenuCreate, MenuUpdate, MenuCategoryCreate, MenuItemCreate,
    MenuItemUpdate, ItemModifierCreate,
)


# --------------- helpers ---------------

def _menu_load_options():
    """Load options for Menu queries — categories→items→modifiers only."""
    return [
        selectinload(Menu.categories)
        .selectinload(MenuCategory.items)
        .selectinload(MenuItem.modifiers),
    ]


def _category_load_options():
    """Load options for MenuCategory queries — items→modifiers only."""
    return [
        selectinload(MenuCategory.items)
        .selectinload(MenuItem.modifiers),
    ]


def _item_load_options():
    """Load options for MenuItem queries — modifiers only."""
    return [
        selectinload(MenuItem.modifiers),
    ]


# --------------- Menu ---------------

class MenuService:
    """Service for Menu operations."""

    @staticmethod
    async def create_menu(session: AsyncSession, menu: MenuCreate) -> Menu:
        db_menu = Menu(**menu.model_dump())
        session.add(db_menu)
        await session.commit()
        stmt = select(Menu).options(*_menu_load_options()).where(Menu.id == db_menu.id)
        result = await session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def get_menu_by_id(session: AsyncSession, menu_id: UUID) -> Optional[Menu]:
        stmt = select(Menu).options(*_menu_load_options()).where(Menu.id == menu_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_menus_by_outlet(session: AsyncSession, outlet_id: UUID) -> list[Menu]:
        stmt = select(Menu).options(*_menu_load_options()).where(Menu.outlet_id == outlet_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_menu(session: AsyncSession, menu_id: UUID, menu_update: MenuUpdate) -> Optional[Menu]:
        db_menu = await MenuService.get_menu_by_id(session, menu_id)
        if db_menu:
            for key, value in menu_update.model_dump(exclude_unset=True).items():
                setattr(db_menu, key, value)
            await session.commit()
            return await MenuService.get_menu_by_id(session, menu_id)
        return None

    @staticmethod
    async def delete_menu(session: AsyncSession, menu_id: UUID) -> bool:
        db_menu = await MenuService.get_menu_by_id(session, menu_id)
        if db_menu:
            await session.delete(db_menu)
            await session.commit()
            return True
        return False


# --------------- MenuCategory ---------------

class MenuCategoryService:
    """Service for MenuCategory operations."""

    @staticmethod
    async def create_category(session: AsyncSession, category: MenuCategoryCreate) -> MenuCategory:
        db_category = MenuCategory(**category.model_dump())
        session.add(db_category)
        await session.commit()
        stmt = select(MenuCategory).options(*_category_load_options()).where(MenuCategory.id == db_category.id)
        result = await session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def get_category_by_id(session: AsyncSession, category_id: UUID) -> Optional[MenuCategory]:
        stmt = select(MenuCategory).options(*_category_load_options()).where(MenuCategory.id == category_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_categories_by_menu(session: AsyncSession, menu_id: UUID) -> list[MenuCategory]:
        stmt = select(MenuCategory).options(*_category_load_options()).where(MenuCategory.menu_id == menu_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete_category(session: AsyncSession, category_id: UUID) -> bool:
        db_category = await MenuCategoryService.get_category_by_id(session, category_id)
        if db_category:
            await session.delete(db_category)
            await session.commit()
            return True
        return False


# --------------- MenuItem ---------------

class MenuItemService:
    """Service for MenuItem operations."""

    @staticmethod
    async def create_item(session: AsyncSession, item: MenuItemCreate) -> MenuItem:
        db_item = MenuItem(**item.model_dump())
        session.add(db_item)
        await session.commit()
        stmt = select(MenuItem).options(*_item_load_options()).where(MenuItem.id == db_item.id)
        result = await session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def get_item_by_id(session: AsyncSession, item_id: UUID) -> Optional[MenuItem]:
        stmt = select(MenuItem).options(*_item_load_options()).where(MenuItem.id == item_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_items_by_category(session: AsyncSession, category_id: UUID) -> list[MenuItem]:
        stmt = select(MenuItem).options(*_item_load_options()).where(MenuItem.category_id == category_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_item(session: AsyncSession, item_id: UUID, item_update: MenuItemUpdate) -> Optional[MenuItem]:
        """Update a menu item — safe re-fetch, no db.refresh."""
        db_item = await MenuItemService.get_item_by_id(session, item_id)
        if db_item:
            for key, value in item_update.model_dump(exclude_unset=True).items():
                setattr(db_item, key, value)
            await session.commit()
            return await MenuItemService.get_item_by_id(session, item_id)
        return None

    @staticmethod
    async def delete_item(session: AsyncSession, item_id: UUID) -> bool:
        db_item = await MenuItemService.get_item_by_id(session, item_id)
        if db_item:
            await session.delete(db_item)
            await session.commit()
            return True
        return False


# --------------- ItemModifier ---------------

class ItemModifierService:
    """Service for ItemModifier operations."""

    @staticmethod
    async def create_modifier(session: AsyncSession, modifier: ItemModifierCreate, menu_item_id: UUID) -> ItemModifier:
        db_modifier = ItemModifier(menu_item_id=menu_item_id, **modifier.model_dump())
        session.add(db_modifier)
        await session.commit()
        # Re-fetch instead of db.refresh to avoid MissingGreenlet
        stmt = select(ItemModifier).where(ItemModifier.id == db_modifier.id)
        result = await session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def get_modifier_by_id(session: AsyncSession, modifier_id: UUID) -> Optional[ItemModifier]:
        result = await session.execute(select(ItemModifier).filter(ItemModifier.id == modifier_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_modifiers_by_item(session: AsyncSession, menu_item_id: UUID) -> list[ItemModifier]:
        result = await session.execute(select(ItemModifier).filter(ItemModifier.menu_item_id == menu_item_id))
        return list(result.scalars().all())

    @staticmethod
    async def delete_modifier(session: AsyncSession, modifier_id: UUID) -> bool:
        db_modifier = await ItemModifierService.get_modifier_by_id(session, modifier_id)
        if db_modifier:
            await session.delete(db_modifier)
            await session.commit()
            return True
        return False