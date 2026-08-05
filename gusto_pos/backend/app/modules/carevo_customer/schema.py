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


class FirebaseAuthIn(BaseModel):
    """Real phone-auth exchange: a Firebase ID token for a CareVo session token.

    The phone number is read from the verified token's claims, never from the
    client — a client-supplied number here would be trivially forgeable.
    """
    id_token: str = Field(..., min_length=16)


class GoogleAuthIn(BaseModel):
    """Google sign-in exchange: a Firebase Google-provider ID token for a CareVo
    session token.

    Same rule as [FirebaseAuthIn] — email and uid are read from the verified
    token's claims, never from the client.
    """
    id_token: str = Field(..., min_length=16)


class CustomerPublic(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    # Optional since Google sign-in: a standalone Google identity has no
    # verified phone until the customer verifies one separately.
    phone_number: Optional[str] = None
    email: Optional[str] = None


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
    upi_id: Optional[str] = None


# ------------------------------ Menu ----------------------------------------
class MenuItemOut(BaseModel):
    id: uuid.UUID
    name: str
    base_price: float
    is_veg: bool
    is_available: bool
    prep_time_minutes: Optional[int] = None
    image_url: Optional[str] = None
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
    # PE Step 3 (FR-C1/C2): travel context captured at checkout.
    transport_mode: Optional[str] = None      # bike | car | walk | auto | bus
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    origin_source: Optional[str] = None        # gps | places_autocomplete | none


# --- PE Step 3: customer event inputs ---------------------------------------
class DepartIn(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None


class LocationPingIn(BaseModel):
    lat: float
    lng: float
    accuracy_m: Optional[float] = None
    speed_mps: Optional[float] = None


class ArrivedIn(BaseModel):
    accuracy_m: Optional[float] = None
    source: str = "geofence"                    # geofence | tap


class WaitFeedbackIn(BaseModel):
    bucket: str = Field(..., pattern=r"^(0|1-3|3-5|5\+)$")


class EventAck(BaseModel):
    ok: bool = True
    recorded: bool = True
    detail: Optional[str] = None


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


class WaitEstimateOut(BaseModel):
    # §16 shadow-mode range only — never a departure window / σ / confidence.
    low_min: int
    high_min: int
    approximate: bool = True


class OrderOut(BaseModel):
    id: uuid.UUID
    status: str
    payment_status: str
    pickup_code: Optional[str] = None
    total_amount: float
    items: list[OrderItemOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    wait_estimate: Optional[WaitEstimateOut] = None


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
    # Payee VPA (e.g. name@bank) for the upi://pay intent. Required for new
    # signups so the outlet can accept payments; simple "x@y" shape check.
    upi_id: str = Field(..., min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")


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
    payment_status: Optional[str] = None
    is_locked: bool
    total_amount: float
    created_at: Optional[datetime] = None
    items: list[OwnerOrderLineOut] = []


class MarkPaidOut(BaseModel):
    order_id: uuid.UUID
    status: str
    payment_status: Optional[str] = None
    pickup_code: Optional[str] = None


class NotifyIn(BaseModel):
    type: str
    item_id: Optional[uuid.UUID] = None


class NotifyOut(BaseModel):
    ok: bool
    delivered: bool
    type: str
    item_id: Optional[uuid.UUID] = None
    item_name: Optional[str] = None
