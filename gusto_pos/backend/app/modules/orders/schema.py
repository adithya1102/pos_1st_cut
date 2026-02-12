"""Pydantic schemas for Order module."""
from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime
from enum import Enum


class OrderStatusEnum(str, Enum):
    """Order status enum."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IN_KITCHEN = "in_kitchen"
    READY = "ready"
    SERVED = "served"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderCreate(BaseModel):
    """Schema for creating an Order."""
    outlet_id: UUID
    table_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    total_amount: float
    order_status: OrderStatusEnum = OrderStatusEnum.PENDING
    kitchen_token: Optional[str] = None


class OrderUpdate(BaseModel):
    """Schema for updating an Order."""
    table_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    total_amount: Optional[float] = None
    order_status: Optional[OrderStatusEnum] = None
    kitchen_token: Optional[str] = None


class OrderRead(BaseModel):
    """Schema for Order response."""
    id: UUID
    readable_id: int
    outlet_id: UUID
    table_id: Optional[UUID]
    customer_id: Optional[UUID]
    total_amount: float
    order_status: OrderStatusEnum
    kitchen_token: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

