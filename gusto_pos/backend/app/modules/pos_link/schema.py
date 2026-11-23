"""Pydantic schemas for the POS registration link (Gusto Skip <-> Native
Gusto POS). See app/modules/pos_link/service.py for the business logic and
migrations/044_pos_registration.sql for the schema."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PosRegistrationCodeOut(BaseModel):
    code: str
    expires_at: datetime


class PosLinkVerifyIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)


class PosLinkOutletOut(BaseModel):
    outlet_id: str
    name: str
    locality: Optional[str] = None
    city: Optional[str] = None


class PosLinkOwnerOut(BaseModel):
    # `name` is the owner's `users.username` -- this codebase has no
    # users.name / full_name column (confirmed: RegisterIn/RegisterOut carry
    # no name field either). Documented here rather than silently treated as
    # a real display name.
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class PosLinkVerifyOut(BaseModel):
    registration_ref: str
    outlet: PosLinkOutletOut
    owner: PosLinkOwnerOut


class PosLinkConsumeIn(BaseModel):
    registration_ref: str = Field(..., min_length=1, max_length=256)
    pos_install_id: str = Field(..., min_length=1, max_length=128)


class PosLinkConsumeOut(BaseModel):
    outlet_id: str
    pos_registered_at: datetime
