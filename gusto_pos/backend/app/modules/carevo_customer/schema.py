"""Pydantic v2 schemas for CareVo Skip customer + payment flows."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ----------------------------- Auth -----------------------------------------
class RequestOtpIn(BaseModel):
    phone_number: str = Field(..., min_length=6, max_length=20)


class RequestOtpOut(BaseModel):
    request_id: str
    stub: bool = True


class VerifyOtpIn(BaseModel):
    phone_number: str = Field(..., min_length=6, max_length=20)
    otp: str


class CustomerPublic(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    phone_number: str


class VerifyOtpOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    customer: CustomerPublic


# --------------------------- Discovery --------------------------------------
class OutletOut(BaseModel):
    id: uuid.UUID
    name: str
    address: Optional[str] = None
    is_open: bool = True
    distance_km: Optional[float] = None


# ------------------------------ Menu ----------------------------------------
class MenuItemOut(BaseModel):
    id: uuid.UUID
    name: str
    base_price: float
    is_veg: bool
    is_available: bool
    prep_time_minutes: Optional[int] = None
    tags: Any = None
    customizations: list[str] = []


class MenuCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    items: list[MenuItemOut] = []


class MenuOut(BaseModel):
    outlet_id: uuid.UUID
    categories: list[MenuCategoryOut] = []


# ----------------------------- Orders ---------------------------------------
class OrderItemIn(BaseModel):
    menu_item_id: uuid.UUID
    quantity: int = Field(..., ge=1)
    customizations: Optional[Any] = None
    item_notes: Optional[str] = None


class CreateOrderIn(BaseModel):
    outlet_id: uuid.UUID
    items: list[OrderItemIn] = Field(..., min_length=1)
    customer_notes: Optional[str] = None


class PaymentBlock(BaseModel):
    gateway: str
    gateway_order_id: str
    amount: int
    currency: str = "INR"
    key_id: Optional[str] = None


class CreateOrderOut(BaseModel):
    id: uuid.UUID
    status: str
    total_amount: float
    payment: PaymentBlock


class OrderItemOut(BaseModel):
    id: uuid.UUID
    menu_item_id: Optional[uuid.UUID] = None
    name_snap: Optional[str] = None
    price_snap: float
    quantity: int
    customizations: Any = None
    item_notes: Optional[str] = None


class OrderOut(BaseModel):
    id: uuid.UUID
    status: str
    payment_status: str
    pickup_code: Optional[str] = None
    total_amount: float
    items: list[OrderItemOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------- Payment ---------------------------------------
class SimulatePaymentIn(BaseModel):
    order_id: uuid.UUID
    method: str = "upi"


class SimulatePaymentOut(BaseModel):
    status: str
    pickup_code: Optional[str] = None


class AdvanceStatusIn(BaseModel):
    status: Optional[str] = None  # optional explicit target; else next in progression


# ------------------------------ POS -----------------------------------------
class VerifyPickupIn(BaseModel):
    order_id: uuid.UUID
    pickup_code: str


class RegisterIn(BaseModel):
    restaurant_name: str = Field(..., min_length=2, max_length=100)
    city: Optional[str] = Field(None, max_length=50)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)


class RegisterOut(BaseModel):
    outlet_id: uuid.UUID
    username: str
    verification_status: str
    message: str


class VerifyPickupOut(BaseModel):
    verified: bool
    order_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    locked: Optional[bool] = None
    attempts_remaining: Optional[int] = None


# --------------------- Owner App (staff-authed POS) -------------------------
class OwnerOutletOut(BaseModel):
    id: uuid.UUID
    location_name: str
    is_visible: bool


class SetVisibilityIn(BaseModel):
    is_visible: bool


class SetVisibilityOut(BaseModel):
    id: uuid.UUID
    is_visible: bool


class OwnerMenuItemOut(BaseModel):
    id: uuid.UUID
    name: str
    is_available: bool
    is_active: bool
    base_price: float
    is_veg: bool = True
    prep_time_minutes: Optional[int] = None
    image_url: Optional[str] = None
    category_id: Optional[uuid.UUID] = None
    category_name: Optional[str] = None


class OwnerCategoryOut(BaseModel):
    id: uuid.UUID
    name: str


class CreateMenuItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    base_price: float = Field(..., ge=0)
    category_id: uuid.UUID
    is_veg: bool = True
    prep_time_minutes: Optional[int] = Field(None, ge=0, le=1440)
    image_url: Optional[str] = Field(None, max_length=1024)


class UpdateMenuItemIn(BaseModel):
    # All optional — a PATCH updates only the fields provided.
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    base_price: Optional[float] = Field(None, ge=0)
    category_id: Optional[uuid.UUID] = None
    is_veg: Optional[bool] = None
    prep_time_minutes: Optional[int] = Field(None, ge=0, le=1440)
    image_url: Optional[str] = Field(None, max_length=1024)
    is_available: Optional[bool] = None


class DeleteMenuItemOut(BaseModel):
    ok: bool
    id: uuid.UUID
    is_active: bool


class SetAvailabilityIn(BaseModel):
    is_available: bool


class SetAvailabilityOut(BaseModel):
    id: uuid.UUID
    is_available: bool


class OwnerOrderLineOut(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    quantity: int


class OwnerOrderOut(BaseModel):
    order_id: uuid.UUID
    status: str
    is_locked: bool
    total_amount: float
    created_at: Optional[datetime] = None
    items: list[OwnerOrderLineOut] = []


class NotifyIn(BaseModel):
    type: str
    item_id: Optional[uuid.UUID] = None


class NotifyOut(BaseModel):
    ok: bool
    delivered: bool
    type: str
    item_id: Optional[uuid.UUID] = None
    item_name: Optional[str] = None
