"""Update organization name to Rudrarthi."""
import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

ORG_ID = "4e1602de-0211-459b-ae4f-b759c512e4e7"

async def update():
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE organizations SET name = 'Rudrarthi' WHERE id = :org_id"),
            {"org_id": ORG_ID}
        )
        await db.commit()
        result = await db.execute(
            text("SELECT name FROM organizations WHERE id = :org_id"),
            {"org_id": ORG_ID}
        )
        row = result.fetchone()
        print(f"Organization name: {row[0]}")

if __name__ == "__main__":
    asyncio.run(update())
