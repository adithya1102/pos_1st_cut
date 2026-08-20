"""Pydantic v2 schemas for the CareVo Admin Dashboard (SUPER_ADMIN-gated)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

VerificationStatus = Literal["pending_verification", "active", "rejected"]


class AdminMeOut(BaseModel):
    user_id: uuid.UUID
    username: str
    is_super_admin: bool
    roles: list[str]


class AdminOutletOut(BaseModel):
    id: uuid.UUID
    location_name: str
    city: Optional[str] = None
    # Area within the city (migration 012). Null for outlets created before it;
    # required at signup from now on. Half of the (city, name, locality) key the
    # approval duplicate guard enforces, so admins need to see it to act on a
    # 409 from that guard.
    locality: Optional[str] = None
    # Contact number (migration 009). NULL for every outlet created before it.
    phone_number: Optional[str] = None
    organization_id: Optional[uuid.UUID] = None
    organization_name: Optional[str] = None
    verification_status: VerificationStatus
    is_visible: bool
    created_at: Optional[datetime] = None
    # Soft-delete (migration 007). Non-null => deactivated/hidden, retained data.
    deactivated_at: Optional[datetime] = None
    is_deactivated: bool = False
    # Owner's login username, so support can help someone who has forgotten
    # BOTH username and password. Read-only; null for an outlet with no active
    # staff row yet. No password material is exposed — only the username, which
    # /auth/password/forgot then accepts to send a reset.
    owner_username: Optional[str] = None


class OutletDecisionIn(BaseModel):
    # Optional free-text captured into the audit trail. Required-in-spirit for
    # rejections, but not enforced — an admin may reject without stating a reason.
    reason: Optional[str] = Field(default=None, max_length=500)


class OutletDecisionOut(BaseModel):
    id: uuid.UUID
    verification_status: VerificationStatus
    previous_status: str


class OutletDeactivateOut(BaseModel):
    id: uuid.UUID
    is_deactivated: bool
    deactivated_at: Optional[datetime] = None


class LockedOrderOut(BaseModel):
    order_id: uuid.UUID
    outlet_id: uuid.UUID
    outlet_name: Optional[str] = None
    status: str
    failed_attempts: int
    total_amount: float
    customer_phone: Optional[str] = None
    created_at: Optional[datetime] = None


class UnlockOrderOut(BaseModel):
    order_id: uuid.UUID
    is_locked: bool
    failed_attempts: int


class AdminOrderItemOut(BaseModel):
    name: Optional[str] = None
    quantity: int = 1


class AdminOrderOut(BaseModel):
    """One order, flattened for the admin log."""

    order_id: uuid.UUID
    pickup_code: Optional[str] = None
    status: str
    payment_status: Optional[str] = None
    created_at: Optional[datetime] = None

    # Nullable since migration 008: an OTP customer has no email, a Google
    # customer has no phone, and a deleted account has neither.
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None

    outlet_name: Optional[str] = None
    items: list[AdminOrderItemOut] = []

    total_amount: float = 0
    discount_amount: float = 0
    promotion_label: Optional[str] = None
    promotion_code: Optional[str] = None
    promotion_discount: Optional[float] = None

    # NULL when the customer never shared an origin. Deliberately not 0 —
    # "unknown" and "at the restaurant" must not render identically.
    distance_km: Optional[float] = None


class AdminOrderPageOut(BaseModel):
    total: int
    limit: int
    offset: int
    orders: list[AdminOrderOut] = []


# ---------------- Restaurant tab: orders grouped restaurant -> day -> time ---
# A VIEW over customer_orders + outlets. No new tables, no new columns — the
# hierarchy is produced by grouping rows that already exist.
class RestaurantOrderOut(BaseModel):
    """One order at the leaf of the restaurant -> day -> time tree."""

    order_id: uuid.UUID
    #: Local wall-clock "HH:MM" — the "time" level of the grouping.
    time: str
    created_at: Optional[datetime] = None
    status: str
    payment_status: Optional[str] = None
    pickup_code: Optional[str] = None
    total_amount: float = 0
    item_count: int = 0


class RestaurantDayOut(BaseModel):
    """One calendar day at one restaurant."""

    #: ISO date, "YYYY-MM-DD".
    day: str
    order_count: int = 0
    total_amount: float = 0
    #: Newest first within the day.
    orders: list[RestaurantOrderOut] = []


class RestaurantGroupOut(BaseModel):
    """One restaurant, with its days nested newest first."""

    outlet_id: Optional[uuid.UUID] = None
    outlet_name: Optional[str] = None
    city: Optional[str] = None
    locality: Optional[str] = None
    order_count: int = 0
    total_amount: float = 0
    days: list[RestaurantDayOut] = []


class AuditLogOut(BaseModel):
    id: uuid.UUID
    actor_username: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[uuid.UUID] = None
    detail: Optional[Any] = None
    created_at: datetime


class CustomerDirectoryOut(BaseModel):
    """One row of the read-only customer directory.

    `name` is nullable because customers are created from a verified identifier
    alone — nothing in the sign-in flow asks for a name.

    `phone_number` and `email` are BOTH nullable as of migration 008: a
    phone-only (OTP) customer has no email, a Google-only customer has no
    phone. The DB CHECK `customers_identity_present` guarantees at least one is
    set, but neither individually. phone_number was `str` here until that
    migration landed — a single Google-only row would have raised a Pydantic
    ValidationError and 500'd this whole endpoint.
    """
    id: uuid.UUID
    phone_number: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    order_count: int
    created_at: Optional[datetime] = None
    # Loyalty + plan (migration 010). `plan` is derived from premium_until on
    # the way out, never stored, so it cannot drift from the timestamp.
    points_balance: float = 0
    premium_until: Optional[datetime] = None
    plan: str = "Free"

    # Order stats, computed from PAID orders only — an abandoned basket is not
    # a purchase and must not inflate lifetime value or recency.
    total_order_value: float = 0
    top_dish: Optional[str] = None
    top_outlet: Optional[str] = None
    last_order_at: Optional[datetime] = None
    days_since_last_order: Optional[int] = None
    # HEURISTIC recency bucket, NOT a churn prediction: "No orders" | "Active"
    # | "At Risk" | "Churned", from days_since_last_order against two fixed
    # thresholds. No model, no training, no probability. See service.py.
    activity_status: str = "No orders"


# ---------------------- Cities (migration 013) -------------------------------
class AdminCityOut(BaseModel):
    id: uuid.UUID
    name: str
    # active | pending | rejected
    status: str
    created_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    # Which outlet's signup asked for it. NULL for seeded/admin-added rows.
    requested_by_outlet_id: Optional[uuid.UUID] = None
    requested_by_outlet_name: Optional[str] = None


class CityDecisionOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    decided_at: Optional[datetime] = None


class CityCreateIn(BaseModel):
    """Admin adds a city directly. No pending state: the admin IS the approval
    authority, so routing their own entry through a queue they alone service is
    ceremony. owner_app's self-service path is unchanged and still gated."""
    name: str = Field(..., min_length=2, max_length=80)


class CityCreateOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    #: False when an existing row was reused rather than a new one inserted.
    #: Reuse is not an error — the caller asked for a city to exist and it does.
    created: bool


class CityRenameIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)


class CityRenameOut(BaseModel):
    id: uuid.UUID
    name: str
    previous_name: str
    status: str
    #: How many `outlets` rows had their denormalised `city` string rewritten.
    #: outlets.city is a varchar, NOT a FK to cities.id — nothing cascades, so
    #: the rename has to carry them explicitly or they are orphaned.
    outlets_updated: int
