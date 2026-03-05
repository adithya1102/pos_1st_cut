"""Migration script to add missing created_at columns to menu_items and item_modifiers tables."""
import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def add_missing_columns():
    async with AsyncSessionLocal() as db:
        try:
            # Add created_at to menu_items
            print("Adding created_at column to menu_items table...")
            await db.execute(text(
                "ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()"
            ))
            
            # Add created_at to item_modifiers
            print("Adding created_at column to item_modifiers table...")
            await db.execute(text(
                "ALTER TABLE item_modifiers ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()"
            ))
            
            await db.commit()
            print("\n✅ Migration completed successfully!")
            
            # Verify
            print("\nVerifying migration...")
            for table in ['menu_items', 'item_modifiers']:
                result = await db.execute(text(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position"
                ))
                cols = [r[0] for r in result.fetchall()]
                print(f"\n{table.upper()}:")
                for col in cols:
                    print(f"  {col}")
                if 'created_at' in cols:
                    print(f"  ✅ created_at column exists")
                else:
                    print(f"  ❌ created_at column still missing!")
                    
        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            await db.rollback()
            raise

asyncio.run(add_missing_columns())
