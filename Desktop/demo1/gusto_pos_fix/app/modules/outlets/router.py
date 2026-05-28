from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.outlets.crud import outlet_crud
from app.modules.outlets.schemas import OutletCreate, OutletRead, OutletUpdate

router = APIRouter(prefix="/outlets", tags=["Outlets"])


@router.post("/", response_model=OutletRead, status_code=status.HTTP_201_CREATED)
async def create_outlet(
    payload: OutletCreate,
    db: AsyncSession = Depends(get_db),
):
    return await outlet_crud.create_outlet(db, payload)


@router.get("/org/{organization_id}", response_model=list[OutletRead])
async def list_outlets(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await outlet_crud.get_outlets_for_org(db, organization_id)


@router.get("/{outlet_id}", response_model=OutletRead)
async def get_outlet(
    outlet_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    outlet = await outlet_crud.get_outlet(db, outlet_id)
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet not found")
    return outlet


@router.patch("/{outlet_id}", response_model=OutletRead)
async def update_outlet(
    outlet_id: UUID,
    payload: OutletUpdate,
    db: AsyncSession = Depends(get_db),
):
    outlet = await outlet_crud.update_outlet(db, outlet_id, payload)
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet not found")
    return outlet


@router.delete("/{outlet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outlet(
    outlet_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    deleted = await outlet_crud.delete(db, outlet_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Outlet not found")
