"""Add ALL missing columns to align DB with ORM models."""
import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text


PATCHES = [
    ("users", "role_id", "ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES roles(id)"),
]


async def patch():
    async with AsyncSessionLocal() as db:
        for table, col, sql in PATCHES:
            # Check if column already exists
            r = await db.execute(
                text(f"SELECT 1 FROM information_schema.columns WHERE table_name='{table}' AND column_name='{col}'")
            )
            if r.fetchone():
                print(f"  {table}.{col}: already exists, skipping")
            else:
                await db.execute(text(sql))
                await db.commit()
                print(f"  {table}.{col}: ADDED")


print("Patching missing columns:")
asyncio.run(patch())
print("Done.")
