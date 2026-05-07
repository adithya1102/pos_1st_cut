"""Seed default staff members. Safe to run multiple times."""
import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.modules.staff.model import Staff, StaffRole

STAFF_SEED = [
    {"name": "Admin",  "role": StaffRole.Admin,  "pin": "0000"},
    {"name": "Waiter", "role": StaffRole.Waiter, "pin": "1111"},
]


async def seed_staff():
    async with AsyncSessionLocal() as db:
        for member in STAFF_SEED:
            result = await db.execute(
                select(Staff).where(Staff.name == member["name"], Staff.role == member["role"])
            )
            if result.scalars().first():
                print(f"  SKIP:    {member['name']} ({member['role'].value}) already exists")
                continue

            db.add(Staff(
                name=member["name"],
                role=member["role"],
                hashed_pin=get_password_hash(member["pin"]),
            ))
            print(f"  CREATED: {member['name']} ({member['role'].value}) PIN={member['pin']}")

        await db.commit()
    print("Staff seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed_staff())
