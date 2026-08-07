"""Schemas for owner account management (migration 015)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChangePasswordIn(BaseModel):
    """Current password is required even though the caller is authenticated —
    a forgotten session must not be enough to seize the account."""
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class SimpleOk(BaseModel):
    ok: bool = True
    message: str = ""


class ForgotPasswordIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)


class ForgotPasswordOut(BaseModel):
    """Deliberately uniform. `ok` and `message` are identical whether or not the
    username exists, so this endpoint cannot be used to enumerate accounts."""
    ok: bool = True
    message: str
    # Null unless there is a real address to hint at, e.g. "a*****a@g****.com".
    email_hint: Optional[str] = None
    # True for legacy accounts with no email: recover via the admin queue.
    needs_admin_help: bool = False


class ResetPasswordIn(BaseModel):
    token: str = Field(..., min_length=16, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=128)


# Pydantic's EmailStr needs the `email-validator` package, which is not a
# dependency here. Rather than add one for a single field, this is a pragmatic
# shape check — the service re-validates, and no format regex substitutes for
# actually delivering to the address, which is what the verification link does.
_EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SetEmailIn(BaseModel):
    email: str = Field(..., min_length=5, max_length=255, pattern=_EMAIL_RE)


class SetEmailOut(BaseModel):
    ok: bool = True
    email: str
    email_hint: Optional[str] = None
    # False while EMAIL_ENABLED is off — the token exists but nothing was sent.
    verification_sent: bool = False


class VerifyEmailIn(BaseModel):
    token: str = Field(..., min_length=16, max_length=256)


class AccountOut(BaseModel):
    username: str
    email: Optional[str] = None
    email_hint: Optional[str] = None
    email_verified: bool = False
    # Drives the "add your email" prompt for accounts predating migration 015.
    needs_email: bool = True
