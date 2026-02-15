from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
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

# FIXED: Removed prefix and tags
router = APIRouter()

# Menu endpoints
@router.post("/", response_model=MenuResponse)
async def create_menu(menu: MenuCreate, db: AsyncSession = Depends(get_db)):
    return await MenuService.create_menu(db, menu)

@router.get("/{menu_id}", response_model=MenuResponse)
async def get_menu(menu_id: UUID, db: AsyncSession = Depends(get_db)):
    menu = await MenuService.get_menu_by_id(db, menu_id)
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
    return menu

@router.get("/outlet/{outlet_id}", response_model=list[MenuResponse])
async def get_outlet_menus(outlet_id: UUID, db: AsyncSession = Depends(get_db)):
    return await MenuService.get_menus_by_outlet(db, outlet_id)

@router.put("/{menu_id}", response_model=MenuResponse)
async def update_menu(menu_id: UUID, menu_update: MenuUpdate, db: AsyncSession = Depends(get_db)):
    menu = await MenuService.update_menu(db, menu_id, menu_update)
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
    return menu

@router.delete("/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_menu(menu_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await MenuService.delete_menu(db, menu_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")

# Menu Category endpoints
@router.post("/categories/", response_model=MenuCategoryResponse)
async def create_category(category: MenuCategoryCreate, db: AsyncSession = Depends(get_db)):
    return await MenuCategoryService.create_category(db, category)

@router.get("/categories/{category_id}", response_model=MenuCategoryResponse)
async def get_category(category_id: UUID, db: AsyncSession = Depends(get_db)):
    category = await MenuCategoryService.get_category_by_id(db, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category

@router.get("/categories/menu/{menu_id}", response_model=list[MenuCategoryResponse])
async def get_menu_categories(menu_id: UUID, db: AsyncSession = Depends(get_db)):
    return await MenuCategoryService.get_categories_by_menu(db, menu_id)

@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await MenuCategoryService.delete_category(db, category_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

# Menu Item endpoints
@router.post("/items/", response_model=MenuItemResponse)
async def create_item(item: MenuItemCreate, db: AsyncSession = Depends(get_db)):
    return await MenuItemService.create_item(db, item)

@router.get("/items/{item_id}", response_model=MenuItemResponse)
async def get_item(item_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await MenuItemService.get_item_by_id(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item

@router.get("/items/category/{category_id}", response_model=list[MenuItemResponse])
async def get_category_items(category_id: UUID, db: AsyncSession = Depends(get_db)):
    return await MenuItemService.get_items_by_category(db, category_id)

@router.put("/items/{item_id}", response_model=MenuItemResponse)
async def update_item(item_id: UUID, item_update: MenuItemUpdate, db: AsyncSession = Depends(get_db)):
    item = await MenuItemService.get_item_by_id(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    update_data = item_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item

@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await MenuItemService.delete_item(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

# Item Modifier endpoints
@router.post("/modifiers/{menu_item_id}", response_model=ItemModifierResponse)
async def create_modifier(menu_item_id: UUID, modifier: ItemModifierCreate, db: AsyncSession = Depends(get_db)):
    return await ItemModifierService.create_modifier(db, modifier, menu_item_id)

@router.get("/modifiers/{modifier_id}", response_model=ItemModifierResponse)
async def get_modifier(modifier_id: UUID, db: AsyncSession = Depends(get_db)):
    modifier = await ItemModifierService.get_modifier_by_id(db, modifier_id)
    if not modifier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modifier not found")
    return modifier

@router.get("/modifiers/item/{menu_item_id}", response_model=list[ItemModifierResponse])
async def get_item_modifiers(menu_item_id: UUID, db: AsyncSession = Depends(get_db)):
    return await ItemModifierService.get_modifiers_by_item(db, menu_item_id)

@router.delete("/modifiers/{modifier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_modifier(modifier_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await ItemModifierService.delete_modifier(db, modifier_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modifier not found")