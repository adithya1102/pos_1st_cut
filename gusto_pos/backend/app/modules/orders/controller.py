from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.orders.model import Order
from app.modules.orders.schema import (
    OrderRead, OrderCreate, OrderUpdate,
    OrderWithItemsRead, SettleResponse, BillResponse,
)
from app.modules.orders.service import OrderService

router = APIRouter(prefix="/orders")


@router.get("/", response_model=list[OrderRead])
async def list_orders(db: AsyncSession = Depends(get_db)):
    """Get all orders."""
    return await OrderService.get_all_orders(db)


@router.get("/table/{table_id}", response_model=list[OrderWithItemsRead])
async def get_table_orders(table_id: str, db: AsyncSession = Depends(get_db)):
    """Get all unpaid orders for a table."""
    orders = await OrderService.get_orders_by_table(db, table_id)
    return orders


@router.get("/history/{outlet_id}")
async def get_order_history(outlet_id: str, date: str = None, table_id: str = None, db: AsyncSession = Depends(get_db)):
    from datetime import datetime
    import datetime as dt
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        target_date = dt.date.today()
    start = datetime.combine(target_date, dt.time.min)
    end = datetime.combine(target_date, dt.time.max)
    query = select(Order).where(
        Order.outlet_id == outlet_id,
        Order.created_at >= start,
        Order.created_at <= end
    ).order_by(Order.created_at.asc())
    if table_id:
        query = query.where(Order.table_id == table_id)
    result = await db.execute(query)
    orders = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "readable_id": getattr(o, "readable_id", None),
            "table_id": o.table_id,
            "total_amount": float(o.total_amount) if o.total_amount else 0,
            "status": o.order_status,
            "payment_method": getattr(o, "payment_method", "cash"),
            "created_at": o.created_at.isoformat() if o.created_at else None
        }
        for o in orders
    ]


@router.get("/summary/{outlet_id}")
async def get_order_summary(outlet_id: str, date: str = None, db: AsyncSession = Depends(get_db)):
    from datetime import datetime
    import datetime as dt
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        target_date = dt.date.today()
    start = datetime.combine(target_date, dt.time.min)
    end = datetime.combine(target_date, dt.time.max)
    result = await db.execute(
        select(Order).where(
            Order.outlet_id == outlet_id,
            Order.created_at >= start,
            Order.created_at <= end
        )
    )
    orders = result.scalars().all()
    total_revenue = sum(float(o.total_amount or 0) for o in orders)
    cash = sum(float(o.total_amount or 0) for o in orders if getattr(o, "payment_method", "cash") == "cash")
    card = sum(float(o.total_amount or 0) for o in orders if getattr(o, "payment_method", "cash") == "card")
    upi = sum(float(o.total_amount or 0) for o in orders if getattr(o, "payment_method", "cash") == "upi")
    active = sum(1 for o in orders if o.order_status != "paid")
    settled = sum(1 for o in orders if o.order_status == "paid")
    return {
        "total_orders": len(orders),
        "total_revenue": total_revenue,
        "cash_total": cash,
        "card_total": card,
        "upi_total": upi,
        "active_orders": active,
        "settled_orders": settled
    }


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


@router.post("/bill/{table_id}", response_model=BillResponse)
async def generate_bill(table_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a PDF bill for all unpaid orders on a table."""
    result = await OrderService.generate_bill(db, table_id)
    if not result:
        raise HTTPException(status_code=404, detail="No unpaid orders found for this table")
    return result


@router.post("/settle/{table_id}", response_model=SettleResponse)
async def settle_table(table_id: str, db: AsyncSession = Depends(get_db)):
    """Mark all unpaid orders for a table as paid."""
    count, total = await OrderService.settle_table(db, table_id)
    return SettleResponse(
        settled_count=count,
        total_amount=total,
        message=f"Table {table_id} settled. {count} orders totalling Rs.{total:.0f}",
    )


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



@router.post("/{order_id}/confirm")
async def confirm_order(order_id: UUID, db: AsyncSession = Depends(get_db)):
    """Confirm an order - updates status from pending to confirmed."""
    obj = await OrderService.get_order_by_id(db, order_id)

    if not obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    obj.order_status = "confirmed"
    await db.commit()

    return {
        "message": "Order confirmed",
        "order_id": str(order_id),
        "status": "confirmed"
    }
