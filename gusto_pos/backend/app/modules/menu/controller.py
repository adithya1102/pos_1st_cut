"""Controller for Menu module."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from app.core.dependencies import get_db
from app.modules.menu.schema import (
    MenuCreate, MenuResponse, MenuUpdate,
    MenuCategoryCreate, MenuCategoryResponse,
    MenuItemCreate, MenuItemResponse, MenuItemUpdate,
    ItemModifierCreate, ItemModifierResponse
)
from app.modules.menu.service import (
    MenuService, MenuCategoryService, MenuItemService, ItemModifierService
)

router = APIRouter(prefix="/menus", tags=["menus"])

DEFAULT_CUSTOMIZATIONS = [
    "No oil", "Less spice", "No butter",
    "No onion", "No garlic", "Jain style",
    "Half portion (1 by 2)", "Extra cheese +\u20b940"
]

# Zone-to-menu mapping for zone-based pricing
ZONE_MENU_MAP = {
    "normal": "dc88b6a6-129c-479f-8609-07b8525f4310",
    "fine_dine": "5ddd464b-f4d3-42d1-a007-10b63659c66f",
}


class PriceRuleUpdate(BaseModel):
    menu_item_id: str
    zone: str
    price: float
    is_available: bool = True


@router.get("/by-zone/{outlet_id}/{zone}", response_model=MenuResponse)
async def get_menu_by_zone(outlet_id: str, zone: str, db: AsyncSession = Depends(get_db)):
    """Get the correct menu for a given zone (normal or fine_dine)."""
    menu_id = ZONE_MENU_MAP.get(zone, ZONE_MENU_MAP["normal"])
    menu = await MenuService.get_menu_by_id(db, UUID(menu_id))
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
    return menu


@router.get("/zone/{outlet_id}/{zone}")
async def get_zone_menu(outlet_id: str, zone: str, db: AsyncSession = Depends(get_db)):
    """Get all categories and items available in a zone via price_rules."""
    result = await db.execute(
        text(
            "SELECT mc.id as cat_id, mc.name as cat_name, "
            "mi.id as item_id, mi.name as item_name, mi.is_veg, "
            "pr.price, pr.is_available "
            "FROM price_rules pr "
            "JOIN menu_items mi ON pr.menu_item_id = mi.id "
            "JOIN menu_categories mc ON mi.category_id = mc.id "
            "JOIN menus m ON mc.menu_id = m.id "
            "WHERE m.outlet_id = :oid AND pr.zone = :zone "
            "AND pr.is_available = true "
            "ORDER BY mc.name, mi.name"
        ),
        {"oid": outlet_id, "zone": zone}
    )
    rows = result.fetchall()
    categories = {}
    for row in rows:
        cat_id = str(row.cat_id)
        if cat_id not in categories:
            categories[cat_id] = {
                "id": cat_id,
                "name": row.cat_name,
                "items": []
            }
        categories[cat_id]["items"].append({
            "id": str(row.item_id),
            "name": row.item_name,
            "price": float(row.price),
            "is_veg": row.is_veg,
            "is_available": row.is_available,
            "customization_options": DEFAULT_CUSTOMIZATIONS
        })
    return {"zone": zone, "categories": list(categories.values())}


@router.patch("/price-rule")
async def update_price_rule(payload: PriceRuleUpdate, db: AsyncSession = Depends(get_db)):
    """Update a specific item's price or availability for a zone."""
    result = await db.execute(
        text(
            "UPDATE price_rules SET price = :price, is_available = :avail "
            "WHERE menu_item_id = :mid AND zone = :zone"
        ),
        {"price": payload.price, "avail": payload.is_available,
         "mid": payload.menu_item_id, "zone": payload.zone}
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Price rule not found")
    await db.commit()
    return {"status": "updated", "menu_item_id": payload.menu_item_id, "zone": payload.zone,
            "price": payload.price, "is_available": payload.is_available}


# Menu endpoints
@router.post("/", response_model=MenuResponse, status_code=status.HTTP_201_CREATED)
async def create_menu(menu: MenuCreate, db: AsyncSession = Depends(get_db)):
    """Create a new menu."""
    return await MenuService.create_menu(db, menu)


@router.get("/{menu_id}", response_model=MenuResponse)
async def get_menu(menu_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a menu by ID."""
    menu = await MenuService.get_menu_by_id(db, menu_id)
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
    return menu


@router.get("/outlet/{outlet_id}", response_model=list[MenuResponse])
async def get_outlet_menus(outlet_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get all menus for an outlet."""
    return await MenuService.get_menus_by_outlet(db, outlet_id)


@router.put("/{menu_id}", response_model=MenuResponse)
async def update_menu(menu_id: UUID, menu_update: MenuUpdate, db: AsyncSession = Depends(get_db)):
    """Update a menu."""
    menu = await MenuService.update_menu(db, menu_id, menu_update)
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
    return menu


@router.delete("/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_menu(menu_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a menu."""
    if not await MenuService.delete_menu(db, menu_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")


# Menu Category endpoints
@router.post("/categories/", response_model=MenuCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(category: MenuCategoryCreate, db: AsyncSession = Depends(get_db)):
    """Create a new menu category."""
    return await MenuCategoryService.create_category(db, category)


@router.get("/categories/{category_id}", response_model=MenuCategoryResponse)
async def get_category(category_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a menu category by ID."""
    category = await MenuCategoryService.get_category_by_id(db, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


@router.get("/categories/menu/{menu_id}", response_model=list[MenuCategoryResponse])
async def get_menu_categories(menu_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get all categories for a menu."""
    return await MenuCategoryService.get_categories_by_menu(db, menu_id)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a menu category."""
    if not await MenuCategoryService.delete_category(db, category_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")


# Menu Item endpoints
@router.post("/items/", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(item: MenuItemCreate, db: AsyncSession = Depends(get_db)):
    """Create a new menu item."""
    return await MenuItemService.create_item(db, item)


@router.get("/items/{item_id}", response_model=MenuItemResponse)
async def get_item(item_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a menu item by ID."""
    item = await MenuItemService.get_item_by_id(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.get("/items/category/{category_id}", response_model=list[MenuItemResponse])
async def get_category_items(category_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get all items in a category."""
    return await MenuItemService.get_items_by_category(db, category_id)


@router.put("/items/{item_id}", response_model=MenuItemResponse)
async def update_item(item_id: UUID, item_update: MenuItemUpdate, db: AsyncSession = Depends(get_db)):
    """Update a menu item (fixed: delegate to service, no inline db.refresh)."""
    item = await MenuItemService.update_item(db, item_id, item_update)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a menu item."""
    if not await MenuItemService.delete_item(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")


# Item Modifier endpoints
@router.post("/modifiers/{menu_item_id}", response_model=ItemModifierResponse, status_code=status.HTTP_201_CREATED)
async def create_modifier(menu_item_id: UUID, modifier: ItemModifierCreate, db: AsyncSession = Depends(get_db)):
    """Create a new item modifier."""
    return await ItemModifierService.create_modifier(db, modifier, menu_item_id)


@router.get("/modifiers/{modifier_id}", response_model=ItemModifierResponse)
async def get_modifier(modifier_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get an item modifier by ID."""
    modifier = await ItemModifierService.get_modifier_by_id(db, modifier_id)
    if not modifier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modifier not found")
    return modifier


@router.get("/modifiers/item/{menu_item_id}", response_model=list[ItemModifierResponse])
async def get_item_modifiers(menu_item_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get all modifiers for a menu item."""
    return await ItemModifierService.get_modifiers_by_item(db, menu_item_id)


@router.delete("/modifiers/{modifier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_modifier(modifier_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete an item modifier."""
    if not await ItemModifierService.delete_modifier(db, modifier_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modifier not found")
