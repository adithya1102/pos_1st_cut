"""Owner account routes: email on file, change password, forgot/reset password.

Split by auth requirement:
  * /api/v1/account/*        staff-authenticated (the owner is signed in)
  * /api/v1/auth/password/*  PUBLIC — by definition a locked-out owner has no
                             token, so these cannot require one

The public pair is the sensitive surface. Both return the SAME response shape
and message regardless of whether the username exists, so neither can be used to
enumerate accounts.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.account import schema as s
from app.modules.account.service import AccountService
from app.modules.carevo_customer.deps import get_current_staff
from app.modules.users.model import User

router = APIRouter(prefix="/account", tags=["Owner Account"])
public_router = APIRouter(prefix="/auth/password", tags=["Owner Account"])


@router.get("", response_model=s.AccountOut)
async def get_account(
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Account state. `needs_email` drives the 'add your email' prompt shown to
    accounts that predate migration 015."""
    return await AccountService.get_account(db, staff)


@router.put("/email", response_model=s.SetEmailOut)
async def set_email(
    payload: s.SetEmailIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Set/update the recovery email and issue a verification link.

    `verification_sent` is false while EMAIL_ENABLED is off: the token is minted
    and recorded, but nothing is delivered. The app surfaces that honestly
    rather than claiming a mail was sent.
    """
    return await AccountService.set_email(db, staff, payload.email)


@router.post("/change-password", response_model=s.SimpleOk)
async def change_password(
    payload: s.ChangePasswordIn,
    staff: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Change password for a signed-in owner.

    Requires the CURRENT password on top of the bearer token — a forgotten
    session on a shared device must not be enough to take over the account.
    Returns 401 if it is wrong.
    """
    return await AccountService.change_password(
        db, staff, payload.current_password, payload.new_password
    )


@public_router.post("/forgot", response_model=s.ForgotPasswordOut)
async def forgot_password(
    payload: s.ForgotPasswordIn,
    db: AsyncSession = Depends(get_db),
):
    """Start a reset from a username alone. PUBLIC by necessity.

    The response is identical for an unknown username, a known one with no
    email, and a known one with email — so it leaks nothing. `email_hint` is
    populated only when there is a real address, and `needs_admin_help` routes
    legacy accounts to the existing admin queue.
    """
    return await AccountService.request_password_reset(db, payload.username)


@public_router.post("/reset", response_model=s.SimpleOk)
async def reset_password(
    payload: s.ResetPasswordIn,
    db: AsyncSession = Depends(get_db),
):
    """Complete a reset with a single-use token. PUBLIC by necessity."""
    return await AccountService.reset_password(db, payload.token, payload.new_password)


@public_router.post("/verify-email", response_model=s.SimpleOk)
async def verify_email(
    payload: s.VerifyEmailIn,
    db: AsyncSession = Depends(get_db),
):
    """Confirm an email address from the link token. PUBLIC: the owner may be
    clicking from a mail client with no session."""
    return await AccountService.verify_email(db, payload.token)
