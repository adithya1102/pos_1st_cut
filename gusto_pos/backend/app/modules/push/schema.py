"""Schemas for push notification registration and nudge triggers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RegisterTokenIn(BaseModel):
    """FCM registration token from the device."""
    fcm_token: str = Field(..., min_length=16, max_length=512)


class RegisterTokenOut(BaseModel):
    ok: bool = True
    # False when the server has no FCM credentials yet: the token is stored, but
    # nothing will actually be delivered until PUSH_ENABLED is configured. The
    # app can surface this honestly instead of implying pushes are live.
    push_configured: bool = False


class NudgeRunOut(BaseModel):
    kind: str
    candidates: int
    sent: int
