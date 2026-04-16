"""Create Fine Dine menu with 30% higher prices."""
import asyncio
from app.core.database import engine
from sqlalchemy import text
import uuid

OUTLET_ID = '0b8a8349-6144-41a8-b028-b9089bd8eaea'
NORMAL_MENU_ID = 'dc88b6a6-129c-479f-8609-07b8525f4310'

async def create_fine_dine_menu():
    async with engine.begin() as conn:
        # Check actual columns
        cat_cols = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'menu_categories' ORDER BY ordinal_position"
        ))
        cat_col_names = [r[0] for r in cat_cols.fetchall()]
        print(f'menu_categories columns: {cat_col_names}')

        item_cols = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'menu_items' ORDER BY ordinal_position"
        ))
        item_col_names = [r[0] for r in item_cols.fetchall()]
        print(f'menu_items columns: {item_col_names}')

        # Create new Fine Dine menu
        fine_dine_id = str(uuid.uuid4())
        await conn.execute(text(
            "INSERT INTO menus (id, outlet_id, version_label, is_latest) "
            "VALUES (:id, :outlet_id, 'fine_dine_v1', false)"
        ), {'id': fine_dine_id, 'outlet_id': OUTLET_ID})

        # Copy categories from normal menu
        cats = await conn.execute(text(
            "SELECT id, name FROM menu_categories WHERE menu_id = :menu_id"
        ), {'menu_id': NORMAL_MENU_ID})

        cat_map = {}
        for cat in cats.fetchall():
            new_cat_id = str(uuid.uuid4())
            cat_map[str(cat.id)] = new_cat_id
            await conn.execute(text(
                "INSERT INTO menu_categories (id, menu_id, name) "
                "VALUES (:id, :menu_id, :name)"
            ), {
                'id': new_cat_id,
                'menu_id': fine_dine_id,
                'name': cat.name,
            })

        # Copy items with 30% price increase
        for old_cat_id, new_cat_id in cat_map.items():
            items = await conn.execute(text(
                "SELECT name, short_code, base_price, is_veg, is_active "
                "FROM menu_items WHERE category_id = :cat_id"
            ), {'cat_id': old_cat_id})

            for item in items.fetchall():
                new_price = round(float(item.base_price or 0) * 1.30)
                new_item_id = str(uuid.uuid4())
                new_code = str(uuid.uuid4())[:8].upper()
                await conn.execute(text(
                    "INSERT INTO menu_items "
                    "(id, category_id, name, short_code, base_price, is_veg, is_active) "
                    "VALUES (:id, :cat_id, :name, :code, :price, :is_veg, :is_active)"
                ), {
                    'id': new_item_id,
                    'cat_id': new_cat_id,
                    'name': item.name,
                    'code': new_code,
                    'price': new_price,
                    'is_veg': item.is_veg,
                    'is_active': item.is_active,
                })

        print(f'Fine Dine menu created: {fine_dine_id}')
        print('Save this ID!')

asyncio.run(create_fine_dine_menu())
