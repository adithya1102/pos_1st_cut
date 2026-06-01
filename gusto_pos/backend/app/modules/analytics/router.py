import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.modules.outlets.model import Table, TableStatus
from app.modules.orders.model import Order
from app.modules.order_items.model import OrderItem

router = APIRouter(prefix="/analytics", tags=["Analytics Dashboard"])


def _today_start() -> datetime:
    """UTC midnight of the current day — used for all today-scoped queries."""
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/free-tables")
async def get_free_tables(
    outlet_id: uuid.UUID = Query(..., description="Outlet UUID"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Table.table_number)
        .where(Table.outlet_id == outlet_id, Table.status == TableStatus.AVAILABLE)
        .order_by(Table.table_number)
    )
    numbers = result.scalars().all()
    return {"count": len(numbers), "table_numbers": numbers}


@router.get("/total-tables")
async def get_total_tables(
    outlet_id: uuid.UUID = Query(..., description="Outlet UUID"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(func.count()).select_from(Table).where(Table.outlet_id == outlet_id)
    )
    return {"count": result.scalar_one()}


@router.get("/top-dish")
async def get_top_dish(
    outlet_id: uuid.UUID = Query(..., description="Outlet UUID"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrderItem.name_snap, func.sum(OrderItem.quantity).label("total_qty"))
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.outlet_id == outlet_id, Order.created_at >= _today_start())
        .group_by(OrderItem.name_snap)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        return {"dish": None, "quantity": 0}
    return {"dish": row.name_snap, "quantity": int(row.total_qty)}


@router.get("/todays-revenue")
async def get_todays_revenue(
    outlet_id: uuid.UUID = Query(..., description="Outlet UUID"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(func.coalesce(func.sum(Order.total_amount), 0))
        .where(
            Order.outlet_id == outlet_id,
            Order.created_at >= _today_start(),
            Order.order_status != "cancelled",
        )
    )
    return {"revenue": float(result.scalar_one())}
