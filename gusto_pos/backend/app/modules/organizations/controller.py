from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.organizations.schema import OrganizationRead, OrganizationCreate, OrganizationUpdate
from app.modules.organizations.service import OrganizationService

router = APIRouter(prefix="/organizations")

@router.get("/", response_model=list[OrganizationRead])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    return await OrganizationService.get_all_organizations(db)

@router.get("/{item_id}", response_model=OrganizationRead)
async def get_organization(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await OrganizationService.get_organization_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return obj

@router.post("/", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(payload: OrganizationCreate, db: AsyncSession = Depends(get_db)):
    return await OrganizationService.create_organization(db, payload)

@router.put("/{item_id}", response_model=OrganizationRead)
async def update_organization(item_id: UUID, payload: OrganizationUpdate, db: AsyncSession = Depends(get_db)):
    obj = await OrganizationService.update_organization(db, item_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await OrganizationService.delete_organization(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")