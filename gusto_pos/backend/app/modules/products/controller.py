from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.products.schema import ProductRead  # Ensure you have this schema
from app.modules.products.service import ProductService
from app.modules.carevo_customer.deps import get_current_staff


# STAFF-ONLY, ROUTER-WIDE.
#
# Every route in this file was reachable with no credentials at all. A caller
# audit across GustoPOS, GustoWaiter, admin_app, owner_app, customer_app,
# gusto_pos/customer_app, dashboard_app and mcp_server found NOTHING calling
# /products — which is what makes closing it router-wide safe here, where the
# same change on orders/ or menus/ would take the tills offline.
#
# Applied on the ROUTER rather than per route, matching customers/ and
# outlets/: a per-route list is a list someone can forget to extend, and the
# next endpoint added to this file would be born unauthenticated.
#
# Exposed before this change: product CRUD.
router = APIRouter(prefix="/products", dependencies=[Depends(get_current_staff)])

@router.get("/", response_model=list[ProductRead])
async def list_products(db: AsyncSession = Depends(get_db)):
    return await ProductService.get_all_products(db)

@router.get("/{item_id}", response_model=ProductRead)
async def get_product(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await ProductService.get_product_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return obj

@router.post("/", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    return await ProductService.create_product(db, payload)

@router.put("/{item_id}", response_model=ProductRead)
async def update_product(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await ProductService.update_product(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await ProductService.delete_product(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")