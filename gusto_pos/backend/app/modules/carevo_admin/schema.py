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
    organization_id: Optional[uuid.UUID] = None
    organization_name: Optional[str] = None
    verification_status: VerificationStatus
    is_visible: bool
    created_at: Optional[datetime] = None
    # Soft-delete (migration 007). Non-null => deactivated/hidden, retained data.
    deactivated_at: Optional[datetime] = None
    is_deactivated: bool = False


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
