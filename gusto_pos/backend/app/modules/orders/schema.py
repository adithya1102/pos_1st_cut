"""Pydantic schemas for Order module."""
from pydantic import BaseModel
from uuid import UUID
from app.modules.order_items.schema import OrderItemRead
from typing import Optional, List
from datetime import datetime
from enum import Enum


class OrderStatusEnum(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IN_KITCHEN = "in_kitchen"
    READY = "ready"
    SERVED = "served"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PAID = "paid"


class OrderItemCreate(BaseModel):
    name: str
    quantity: int
    unit_price: float
    customizations: Optional[List[str]] = []
    custom_note: Optional[str] = None


class OrderCreate(BaseModel):
    outlet_id: UUID
    table_id: Optional[str] = None
    customer_id: Optional[UUID] = None
    staff_id: Optional[UUID] = None
    total_amount: float
    order_status: OrderStatusEnum = OrderStatusEnum.PENDING
    kitchen_token: Optional[str] = None
    items: Optional[List[OrderItemCreate]] = []


class OrderUpdate(BaseModel):
    table_id: Optional[str] = None
    customer_id: Optional[UUID] = None
    total_amount: Optional[float] = None
    order_status: Optional[OrderStatusEnum] = None
    kitchen_token: Optional[str] = None
    items: Optional[List[OrderItemCreate]] = None


class OrderRead(BaseModel):
    id: UUID
    readable_id: int
    outlet_id: UUID
    table_id: Optional[str]
    customer_id: Optional[UUID]
    total_amount: float
    order_status: OrderStatusEnum
    kitchen_token: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class OrderWithItemsRead(BaseModel):
    id: UUID
    readable_id: int
    outlet_id: UUID
    table_id: Optional[str]
    total_amount: float
    order_status: str
    created_at: datetime
    items: list[OrderItemRead] = []

    class Config:
        from_attributes = True


class SettleResponse(BaseModel):
    settled_count: int
    total_amount: float
    message: str


class BillResponse(BaseModel):
    pdf_path: str
    total: float
    items: list[dict]
    bill_no: str
