# from typing import Any
# from uuid import UUID

# from fastapi import APIRouter, Depends, HTTPException, status, Body
# from sqlalchemy import select
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.modules.orders.schema import OrderRead
# from app.modules.orders.model import Order
# # 1. Import get_db directly instead of the dependency wrapper
# from app.core.database import get_db

# # 2. Removed tags=["orders"] to prevent duplicate Swagger UI sections
# router = APIRouter(prefix="/orders")


# @router.get("/", response_model=list[OrderRead])
# async def list_orders(db: AsyncSession = Depends(get_db)): # Fixed dependency injection
#     result = await db.execute(select(Order))
#     return result.scalars().all()


# @router.get("/{item_id}", response_model=OrderRead)
# async def get_order(item_id: UUID, db: AsyncSession = Depends(get_db)):
#     obj = await db.get(Order, item_id)
#     if not obj:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
#     return obj


# @router.post("/", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
# async def create_order(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
#     # Note: Consider creating an OrderCreate schema in the future instead of dict[str, Any]
#     obj = Order(**payload)
#     db.add(obj)
#     await db.commit()
#     await db.refresh(obj)
#     return obj


# @router.put("/{item_id}", response_model=OrderRead)
# async def update_order(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
#     obj = await db.get(Order, item_id)
#     if not obj:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
#     for k, v in payload.items():
#         setattr(obj, k, v)
#     db.add(obj)
#     await db.commit()
#     await db.refresh(obj)
#     return obj


# @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_order(item_id: UUID, db: AsyncSession = Depends(get_db)):
#     obj = await db.get(Order, item_id)
#     if not obj:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
#     await db.delete(obj)
#     await db.commit()

from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.orders.schema import OrderRead, OrderCreate, OrderUpdate
from app.modules.orders.service import OrderService

router = APIRouter(prefix="/orders")

@router.get("/", response_model=list[OrderRead])
async def list_orders(db: AsyncSession = Depends(get_db)):
    """Get all orders."""
    return await OrderService.get_all_orders(db)

@router.get("/{item_id}", response_model=OrderRead)
async def get_order(item_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get an order by ID."""
    obj = await OrderService.get_order_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return obj

@router.post("/", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(payload: OrderCreate, db: AsyncSession = Depends(get_db)):
    """Create a new order."""
    return await OrderService.create_order(db, payload)

@router.put("/{item_id}", response_model=OrderRead)
async def update_order(item_id: UUID, payload: OrderUpdate, db: AsyncSession = Depends(get_db)):
    """Update an order."""
    obj = await OrderService.update_order(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(item_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete an order."""
    success = await OrderService.delete_order(db, item_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")