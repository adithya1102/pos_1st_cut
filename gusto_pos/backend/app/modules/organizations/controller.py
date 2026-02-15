from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.organizations.schema import OrganizationRead, OrganizationCreate
from app.modules.organizations.model import Organization
from app.core.database import get_db

# FIXED: Removed prefix and tags
router = APIRouter()

@router.get("/", response_model=list[OrganizationRead])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Organization))
    return result.scalars().all()

@router.get("/{item_id}", response_model=OrganizationRead)
async def get_organization(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Organization, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return obj

@router.post("/", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(payload: OrganizationCreate, db: AsyncSession = Depends(get_db)):
    obj = Organization(name=payload.name, gst_number=payload.gst_number)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.put("/{item_id}", response_model=OrganizationRead)
async def update_organization(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await db.get(Organization, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Organization, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    await db.delete(obj)
    await db.commit()