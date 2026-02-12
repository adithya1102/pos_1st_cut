"""Service layer for Menu operations."""
from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.menu.model import Menu, MenuCategory, MenuItem, ItemModifier
from app.modules.menu.schema import MenuCreate, MenuUpdate, MenuCategoryCreate, MenuItemCreate, ItemModifierCreate


class MenuService:
    """Service for Menu operations."""

    @staticmethod
    async def create_menu(session: AsyncSession, menu: MenuCreate) -> Menu:
        """Create a new menu."""
        db_menu = Menu(**menu.model_dump())
        session.add(db_menu)
        await session.commit()
        await session.refresh(db_menu)
        return db_menu

    @staticmethod
    async def get_menu_by_id(session: AsyncSession, menu_id: UUID) -> Optional[Menu]:
        """Get a menu by ID."""
        result = await session.execute(select(Menu).filter(Menu.id == menu_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_menus_by_outlet(session: AsyncSession, outlet_id: UUID) -> list[Menu]:
        """Get all menus for an outlet."""
        result = await session.execute(select(Menu).filter(Menu.outlet_id == outlet_id))
        return result.scalars().all()

    @staticmethod
    async def update_menu(session: AsyncSession, menu_id: UUID, menu_update: MenuUpdate) -> Optional[Menu]:
        """Update a menu."""
        db_menu = await MenuService.get_menu_by_id(session, menu_id)
        if db_menu:
            update_data = menu_update.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_menu, key, value)
            await session.commit()
            await session.refresh(db_menu)
        return db_menu

    @staticmethod
    async def delete_menu(session: AsyncSession, menu_id: UUID) -> bool:
        """Delete a menu."""
        db_menu = await MenuService.get_menu_by_id(session, menu_id)
        if db_menu:
            await session.delete(db_menu)
            await session.commit()
            return True
        return False


class MenuCategoryService:
    """Service for MenuCategory operations."""

    @staticmethod
    async def create_category(session: AsyncSession, category: MenuCategoryCreate) -> MenuCategory:
        """Create a new menu category."""
        db_category = MenuCategory(**category.model_dump())
        session.add(db_category)
        await session.commit()
        await session.refresh(db_category)
        return db_category

    @staticmethod
    async def get_category_by_id(session: AsyncSession, category_id: UUID) -> Optional[MenuCategory]:
        """Get a menu category by ID."""
        result = await session.execute(select(MenuCategory).filter(MenuCategory.id == category_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_categories_by_menu(session: AsyncSession, menu_id: UUID) -> list[MenuCategory]:
        """Get all categories for a menu."""
        result = await session.execute(select(MenuCategory).filter(MenuCategory.menu_id == menu_id))
        return result.scalars().all()

    @staticmethod
    async def delete_category(session: AsyncSession, category_id: UUID) -> bool:
        """Delete a menu category."""
        db_category = await MenuCategoryService.get_category_by_id(session, category_id)
        if db_category:
            await session.delete(db_category)
            await session.commit()
            return True
        return False


class MenuItemService:
    """Service for MenuItem operations."""

    @staticmethod
    async def create_item(session: AsyncSession, item: MenuItemCreate) -> MenuItem:
        """Create a new menu item."""
        db_item = MenuItem(**item.model_dump())
        session.add(db_item)
        await session.commit()
        await session.refresh(db_item)
        return db_item

    @staticmethod
    async def get_item_by_id(session: AsyncSession, item_id: UUID) -> Optional[MenuItem]:
        """Get a menu item by ID."""
        result = await session.execute(select(MenuItem).filter(MenuItem.id == item_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_items_by_category(session: AsyncSession, category_id: UUID) -> list[MenuItem]:
        """Get all items in a category."""
        result = await session.execute(select(MenuItem).filter(MenuItem.category_id == category_id))
        return result.scalars().all()

    @staticmethod
    async def delete_item(session: AsyncSession, item_id: UUID) -> bool:
        """Delete a menu item."""
        db_item = await MenuItemService.get_item_by_id(session, item_id)
        if db_item:
            await session.delete(db_item)
            await session.commit()
            return True
        return False


class ItemModifierService:
    """Service for ItemModifier operations."""

    @staticmethod
    async def create_modifier(session: AsyncSession, modifier: ItemModifierCreate, menu_item_id: UUID) -> ItemModifier:
        """Create a new item modifier."""
        db_modifier = ItemModifier(menu_item_id=menu_item_id, **modifier.model_dump())
        session.add(db_modifier)
        await session.commit()
        await session.refresh(db_modifier)
        return db_modifier

    @staticmethod
    async def get_modifier_by_id(session: AsyncSession, modifier_id: UUID) -> Optional[ItemModifier]:
        """Get an item modifier by ID."""
        result = await session.execute(select(ItemModifier).filter(ItemModifier.id == modifier_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_modifiers_by_item(session: AsyncSession, menu_item_id: UUID) -> list[ItemModifier]:
        """Get all modifiers for a menu item."""
        result = await session.execute(select(ItemModifier).filter(ItemModifier.menu_item_id == menu_item_id))
        return result.scalars().all()

    @staticmethod
    async def delete_modifier(session: AsyncSession, modifier_id: UUID) -> bool:
        """Delete an item modifier."""
        db_modifier = await ItemModifierService.get_modifier_by_id(session, modifier_id)
        if db_modifier:
            await session.delete(db_modifier)
            await session.commit()
            return True
        return False
