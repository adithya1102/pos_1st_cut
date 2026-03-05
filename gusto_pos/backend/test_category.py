"""Test script to reproduce the category creation 500 error."""
import asyncio
import sys
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.modules.menu.service import MenuCategoryService
from app.modules.menu.schema import MenuCategoryCreate

async def test_category_creation():
    """Test creating a category and see if we get an error."""
    async with AsyncSessionLocal() as db:
        # First, get a valid menu_id from the database
        from sqlalchemy import text, select
        from app.modules.menu.model import Menu
        
        result = await db.execute(select(Menu).limit(1))
        menu = result.scalar_one_or_none()
        
        if not menu:
            print("ERROR: No menus found in database. Please create a menu first.")
            sys.exit(1)
        
        menu_id = menu.id
        print(f"Using menu_id: {menu_id}")
        
        # Now try to create a category
        try:
            category_data = MenuCategoryCreate(
                menu_id=menu_id,
                name="Test Starters"
            )
            
            print("\nAttempting to create category...")
            category = await MenuCategoryService.create_category(db, category_data)
            
            print(f"\n✅ SUCCESS! Category created:")
            print(f"  ID: {category.id}")
            print(f"  Menu ID: {category.menu_id}")
            print(f"  Name: {category.name}")
            print(f"  Created at: {category.created_at}")
            
            # Try to access the items relationship
            print(f"  Items: {category.items}")
            
            # Now try to serialize it like FastAPI would
            from app.modules.menu.schema import MenuCategoryResponse
            try:
                response = MenuCategoryResponse.model_validate(category)
                print(f"\n✅ Serialization successful!")
                print(f"Response JSON: {response.model_dump_json(indent=2)}")
            except Exception as e:
                print(f"\n❌ SERIALIZATION FAILED!")
                print(f"Error type: {type(e).__name__}")
                print(f"Error message: {e}")
                import traceback
                traceback.print_exc()
                
        except Exception as e:
            print(f"\n❌ CREATION FAILED!")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_category_creation())
