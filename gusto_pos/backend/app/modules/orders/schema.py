"""Pydantic schemas for Order module."""
from pydantic import BaseModel, Field
from uuid import UUID
from app.modules.order_items.schema import OrderItemRead
from typing import Optional, List
from datetime import datetime
from enum import Enum


class OrderStatusEnum(str, Enum):
    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    CONFIRMED = "confirmed"
    IN_KITCHEN = "in_kitchen"
    READY = "ready"
    SERVED = "served"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PAID = "paid"


class OrderItemCreate(BaseModel):
    """A requested line. The CALLER names the item and the quantity; the SERVER
    decides what it costs.

    WHAT CHANGED AND WHY
    --------------------
    This used to be `{name, quantity, unit_price}` with no `menu_item_id` at
    all, which meant there was nothing on the server to price against — the
    money came off the wire. Combined with POST /orders/ being unauthenticated,
    a verified request of

        {"items":[{"name":"Chicken Biryani","quantity":5,"unit_price":0.002}],
         "total_amount":0.01}

    was accepted and stored: orders.total_amount = 0.01, order_items.price_snap
    = 0.00, for five of a real dish.

    `menu_item_id` is now required and the price is resolved from
    menu_items.base_price, which is exactly what the CareVo customer path has
    always done (carevo_customer/service.py — same SELECT, same 409 on an
    unavailable item).

    `name` stays OPTIONAL and is ignored for pricing. It is retained only so
    an existing caller's payload still parses; the stored name_snap comes from
    the menu row, not from the request.
    """

    menu_item_id: UUID
    quantity: int = Field(..., gt=0, description="Must be positive")
    #: Ignored. Kept so legacy payloads still validate; name_snap is taken from
    #: the menu row.
    name: Optional[str] = None
    customizations: Optional[List[str]] = []
    custom_note: Optional[str] = None

    # `unit_price` is REFUSED here, not ignored. A caller that still sends it
    # is told so, rather than being left to believe it chose the price.
    model_config = {"extra": "forbid"}


class OrderCreate(BaseModel):
    """`total_amount` is GONE from the input.

    It was a required client-supplied field that the server stored verbatim and
    never cross-checked against the lines. The total is now computed from the
    resolved per-item prices, so there is no way to declare one.
    """

    outlet_id: UUID
    table_id: Optional[str] = None
    customer_id: Optional[UUID] = None
    order_status: OrderStatusEnum = OrderStatusEnum.PENDING
    items: Optional[List[OrderItemCreate]] = []
    source: str = "pos"
    waiter_order_id: Optional[UUID] = None
    needs_waiter_approval: Optional[bool] = None
    # Carried on the event payloads only — orders are not zone-scoped in the DB
    zone: Optional[str] = "normal"
    order_type: Optional[str] = "dine_in"

    # A client that still sends total_amount is REFUSED rather than silently
    # ignored: accepting and discarding it would leave the caller believing it
    # set the price. Same for unit_price inside items, caught by
    # OrderItemCreate's own config.
    model_config = {"extra": "forbid"}


class ConfirmResponse(BaseModel):
    message: str
    order_id: str
    status: str


class OrderUpdate(BaseModel):
    """`total_amount` is GONE here too.

    PUT /orders/{id} accepted an arbitrary new total for an existing order and
    wrote it straight through, which made the pricing fix on POST pointless on
    its own: create honestly, then overwrite the total. The total is derived
    from the order's lines and is only ever recomputed by the server (see
    replace_order_items).
    """

    table_id: Optional[str] = None
    customer_id: Optional[UUID] = None
    order_status: Optional[OrderStatusEnum] = None

    model_config = {"extra": "forbid"}


class OrderItemsUpdate(BaseModel):
    items: List[OrderItemCreate]


class OrderRead(BaseModel):
    id: UUID
    readable_id: int
    outlet_id: UUID
    table_id: Optional[str]
    customer_id: Optional[UUID]
    total_amount: float
    order_status: OrderStatusEnum
    source: str = "pos"
    needs_waiter_approval: bool = False
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
    source: str = "pos"
    needs_waiter_approval: bool = False
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
