import uuid
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core.database import AsyncSessionLocal

router = APIRouter(prefix="/orders")


class OrderCreateSchema(BaseModel):
    table_id: str
    items: List = []
    total_amount: float
    outlet_id: Optional[str] = None


@router.post("/")
async def create_order(payload: OrderCreateSchema):
    order_id = str(uuid.uuid4())
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "INSERT INTO orders "
                    "(id, outlet_id, table_id, total_amount, order_status, created_at) "
                    "VALUES (:id, :outlet_id, :table_id, :total_amount, 'pending', NOW())"
                ),
                {
                    "id": order_id,
                    "outlet_id": payload.outlet_id,
                    "table_id": payload.table_id,
                    "total_amount": payload.total_amount,
                },
            )
            await session.commit()
    except Exception as exc:
        return {
            "status": "error",
            "detail": str(exc),
            "order_id": None,
            "total_amount": payload.total_amount,
        }

    return {
        "status": "ok",
        "order_id": order_id,
        "total_amount": payload.total_amount,
    }
