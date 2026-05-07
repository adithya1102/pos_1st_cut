"""
Create the staff table and seed default Admin + Waiter accounts.
Safe to run multiple times — checks for existing entries before inserting.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.core.database import engine, AsyncSessionLocal
from app.modules.staff.model import Staff, StaffRole, Base
from app.core.security import get_password_hash


async def run():
    # Create the staff table (and staffrole enum type) if not already present
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] staff table ready")

    defaults = [
        {"name": "Admin",  "role": StaffRole.Admin,  "pin": "0000"},
        {"name": "Waiter", "role": StaffRole.Waiter,  "pin": "1111"},
    ]

    async with AsyncSessionLocal() as db:
        for entry in defaults:
            result = await db.execute(
                text("SELECT id FROM staff WHERE name = :name AND role = :role"),
                {"name": entry["name"], "role": entry["role"].value},
            )
            if result.fetchone():
                print(f"  SKIP  {entry['role'].value}: {entry['name']} (already exists)")
                continue

            member = Staff(
                name=entry["name"],
                role=entry["role"],
                hashed_pin=get_password_hash(entry["pin"]),
            )
            db.add(member)
            print(f"  ADDED {entry['role'].value}: {entry['name']} (PIN {entry['pin']})")

        await db.commit()

    print("[OK] Staff seed complete")


if __name__ == "__main__":
    asyncio.run(run())
