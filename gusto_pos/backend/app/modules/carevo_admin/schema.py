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
