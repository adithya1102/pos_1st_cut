from uuid import UUID
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.organizations.model import Organization
from app.modules.organizations.schema import OrganizationCreate

class OrganizationService:
    @staticmethod
    async def get_all_organizations(db: AsyncSession):
        result = await db.execute(select(Organization))
        return result.scalars().all()

    @staticmethod
    async def get_organization_by_id(db: AsyncSession, org_id: UUID) -> Optional[Organization]:
        stmt = select(Organization).where(Organization.id == org_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_organization(db: AsyncSession, payload: OrganizationCreate):
        obj = Organization(name=payload.name, gst_number=payload.gst_number)
        db.add(obj)
        await db.commit()
        # Re-fetch with eager loading to prevent serialization errors
        return await OrganizationService.get_organization_by_id(db, obj.id)

    @staticmethod
    async def update_organization(db: AsyncSession, org_id: UUID, payload: dict[str, Any]):
        obj = await OrganizationService.get_organization_by_id(db, org_id)
        if not obj:
            return None
        for k, v in payload.items():
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        # Re-fetch with eager loading to prevent serialization errors
        return await OrganizationService.get_organization_by_id(db, org_id)

    @staticmethod
    async def delete_organization(db: AsyncSession, org_id: UUID) -> bool:
        obj = await OrganizationService.get_organization_by_id(db, org_id)
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True