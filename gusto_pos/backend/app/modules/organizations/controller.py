from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.organizations.schema import OrganizationRead, OrganizationCreate, OrganizationUpdate
from app.modules.organizations.service import OrganizationService
from app.modules.carevo_customer.deps import get_current_staff


# STAFF-ONLY, ROUTER-WIDE.
#
# Every route in this file was reachable with no credentials at all. A caller
# audit across GustoPOS, GustoWaiter, admin_app, owner_app, customer_app,
# gusto_pos/customer_app, dashboard_app and mcp_server found NOTHING calling
# /organizations — which is what makes closing it router-wide safe here, where the
# same change on orders/ or menus/ would take the tills offline.
#
# Applied on the ROUTER rather than per route, matching customers/ and
# outlets/: a per-route list is a list someone can forget to extend, and the
# next endpoint added to this file would be born unauthenticated.
#
# Exposed before this change: org CRUD including unauthenticated DELETE at the top of the tenancy hierarchy.
router = APIRouter(prefix="/organizations", dependencies=[Depends(get_current_staff)])

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