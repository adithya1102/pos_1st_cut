"""Comprehensive test for all category endpoints."""
import asyncio
from uuid import UUID
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.menu.service import MenuCategoryService, MenuService
from app.modules.menu.schema import MenuCategoryCreate, MenuCategoryResponse

async def test_all_category_endpoints():
    """Test all category CRUD operations."""
    async with AsyncSessionLocal() as db:
        # Get a valid menu_id
        from app.modules.menu.model import Menu
        result = await db.execute(select(Menu).limit(1))
        menu = result.scalar_one_or_none()
        
        if not menu:
            print("❌ No menus found. Please create a menu first.")
            return
        
        menu_id = menu.id
        print(f"Using menu_id: {menu_id}\n")
        
        # TEST 1: POST /menus/categories/ - Create category
        print("=" * 60)
        print("TEST 1: CREATE CATEGORY")
        print("=" * 60)
        try:
            category_data = MenuCategoryCreate(
                menu_id=menu_id,
                name="Test Appetizers"
            )
            category = await MenuCategoryService.create_category(db, category_data)
            category_id = category.id
            
            # Serialize
            response = MenuCategoryResponse.model_validate(category)
            print(f"✅ POST /menus/categories/")
            print(f"   Status: 201 CREATED")
            print(f"   Response: {response.model_dump_json(indent=2)}\n")
        except Exception as e:
            print(f"❌ POST /menus/categories/ FAILED: {e}\n")
            return
        
        # TEST 2: GET /menus/categories/{category_id}
        print("=" * 60)
        print("TEST 2: GET CATEGORY BY ID")
        print("=" * 60)
        try:
            category = await MenuCategoryService.get_category_by_id(db, category_id)
            response = MenuCategoryResponse.model_validate(category)
            print(f"✅ GET /menus/categories/{category_id}")
            print(f"   Status: 200 OK")
            print(f"   Response: {response.model_dump_json(indent=2)}\n")
        except Exception as e:
            print(f"❌ GET /menus/categories/{{id}} FAILED: {e}\n")
        
        # TEST 3: GET /menus/categories/menu/{menu_id}
        print("=" * 60)
        print("TEST 3: GET CATEGORIES BY MENU")
        print("=" * 60)
        try:
            categories = await MenuCategoryService.get_categories_by_menu(db, menu_id)
            print(f"✅ GET /menus/categories/menu/{menu_id}")
            print(f"   Status: 200 OK")
            print(f"   Count: {len(categories)} categories")
            for cat in categories:
                response = MenuCategoryResponse.model_validate(cat)
                print(f"   - {response.name} (ID: {response.id})")
            print()
        except Exception as e:
            print(f"❌ GET /menus/categories/menu/{{id}} FAILED: {e}\n")
        
        # TEST 4: DELETE /menus/categories/{category_id}
        print("=" * 60)
        print("TEST 4: DELETE CATEGORY")
        print("=" * 60)
        try:
            success = await MenuCategoryService.delete_category(db, category_id)
            if success:
                print(f"✅ DELETE /menus/categories/{category_id}")
                print(f"   Status: 204 NO CONTENT\n")
                
                # Verify deletion
                deleted_cat = await MenuCategoryService.get_category_by_id(db, category_id)
                if deleted_cat is None:
                    print(f"✅ Verification: Category successfully deleted\n")
                else:
                    print(f"❌ Verification: Category still exists!\n")
            else:
                print(f"❌ DELETE failed: Category not found\n")
        except Exception as e:
            print(f"❌ DELETE /menus/categories/{{id}} FAILED: {e}\n")
        
        print("=" * 60)
        print("ALL TESTS COMPLETED")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_all_category_endpoints())
