from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.menu.crud import menu_crud
from app.modules.menu.schemas import MenuCreate, MenuRead, MenuUpdate

router = APIRouter(prefix="/menus", tags=["Menus"])


@router.post("/", response_model=MenuRead, status_code=status.HTTP_201_CREATED)
async def create_menu(
    payload: MenuCreate,
    db: AsyncSession = Depends(get_db),
):
    menu = await menu_crud.create_menu(db, payload)
    return menu


@router.get("/outlet/{outlet_id}", response_model=list[MenuRead])
async def list_menus_for_outlet(
    outlet_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await menu_crud.get_menus_for_outlet(db, outlet_id)


@router.get("/{menu_id}", response_model=MenuRead)
async def get_menu(
    menu_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    menu = await menu_crud.get_with_full_load(db, menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")
    return menu


@router.patch("/{menu_id}", response_model=MenuRead)
async def update_menu(
    menu_id: UUID,
    payload: MenuUpdate,
    db: AsyncSession = Depends(get_db),
):
    menu = await menu_crud.update_menu(db, menu_id, payload)
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")
    return menu


@router.delete("/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_menu(
    menu_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    deleted = await menu_crud.delete(db, menu_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Menu not found")
