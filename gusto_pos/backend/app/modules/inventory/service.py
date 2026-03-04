from uuid import UUID
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.inventory.model import Inventory

class InventoryService:
    @staticmethod
    async def get_all_inventory(db: AsyncSession):
        result = await db.execute(select(Inventory))
        return result.scalars().all()

    @staticmethod
    async def get_inventory_by_id(db: AsyncSession, inventory_id: UUID):
        return await db.get(Inventory, inventory_id)

    @staticmethod
    async def create_inventory(db: AsyncSession, payload: dict[str, Any]):
        obj = Inventory(**payload)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def update_inventory(db: AsyncSession, inventory_id: UUID, payload: dict[str, Any]):
        obj = await db.get(Inventory, inventory_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @staticmethod
    async def delete_inventory(db: AsyncSession, inventory_id: UUID) -> bool:
        obj = await db.get(Inventory, inventory_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True