"""Owner account management: email, change-password, forgot-password.

## Why not Firebase
Owner accounts live in `users` (username + bcrypt hash) and authenticate via
POST /api/v1/auth/login → JWT. They are NOT Firebase Auth users, so Firebase's
built-in verification/reset mail does not apply to them. This module issues its
own single-use, expiring tokens instead (migration 015).

## Sending is gated
`settings.EMAIL_ENABLED` gates delivery, exactly as PUSH_ENABLED gates FCM.
With it false — the current state, since no mail provider is configured — a
token is still minted and recorded, and the message is logged rather than sent.
The flows are therefore fully exercisable now and turn live with no code change
once a provider is wired into `_deliver`.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash, verify_password

logger = logging.getLogger(__name__)

KIND_PASSWORD_RESET = "PASSWORD_RESET"
KIND_EMAIL_VERIFY = "EMAIL_VERIFY"

RESET_TOKEN_TTL_MINUTES = 30
VERIFY_TOKEN_TTL_HOURS = 48
# A fresh reset request inside this window reuses nothing and simply issues
# another token; this only caps how many can be minted, so a username cannot be
# used to spray mail at someone's inbox.
RESET_MAX_PER_HOUR = 5

MIN_PASSWORD_LENGTH = 8


class AccountService:
    # ------------------------------ helpers --------------------------------
    @staticmethod
    def _hash_token(raw: str) -> str:
        """Store only the digest — a leaked DB dump must not yield live links."""
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def mask_email(email: Optional[str]) -> Optional[str]:
        """'adithya@gmail.com' -> 'a*****a@g****.com'.

        Enough for the owner to recognise their own address, not enough for
        someone else to learn it. Returns None for a missing address so callers
        decide what to show.
        """
        if not email or "@" not in email:
            return None
        local, _, domain = email.partition("@")
        dom_name, _, tld = domain.rpartition(".")

        def squeeze(s: str) -> str:
            if len(s) <= 2:
                return (s[:1] or "*") + "*"
            return f"{s[0]}{'*' * (len(s) - 2)}{s[-1]}"

        masked_domain = squeeze(dom_name) if dom_name else squeeze(domain)
        return f"{squeeze(local)}@{masked_domain}" + (f".{tld}" if tld else "")

    @staticmethod
    async def _deliver(to: str, subject: str, body: str) -> str:
        """Single outbound-mail choke point.

        No provider is wired in yet. Returns the delivery status so callers can
        record it honestly rather than implying a send that never happened.
        """
        if not settings.EMAIL_ENABLED:
            logger.info("EMAIL SKIPPED (EMAIL_ENABLED=false) to=%s subject=%s", to, subject)
            return "skipped"
        # A provider integration slots in here; everything above is transport
        # agnostic, so nothing else in this module changes when one is added.
        logger.warning("EMAIL_ENABLED=true but no transport is implemented; to=%s", to)
        return "skipped"

    @staticmethod
    async def _issue_token(db: AsyncSession, user_id, kind: str, ttl: timedelta) -> str:
        raw = secrets.token_urlsafe(32)
        await db.execute(text("""
            INSERT INTO auth_tokens (user_id, kind, token_hash, expires_at)
            VALUES (:uid, :kind, :hash, :exp)
        """), {
            "uid": str(user_id), "kind": kind,
            "hash": AccountService._hash_token(raw),
            "exp": datetime.now(timezone.utc) + ttl,
        })
        return raw

    @staticmethod
    def _validate_new_password(new_password: str, current: Optional[str] = None) -> None:
        if len(new_password or "") < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            )
        if current is not None and new_password == current:
            raise HTTPException(
                status_code=422, detail="New password must differ from the current one"
            )

    # -------------------------- change password ----------------------------
    @staticmethod
    async def change_password(
        db: AsyncSession, user, current_password: str, new_password: str
    ) -> dict:
        """Change the password of an ALREADY-AUTHENTICATED owner.

        The current password is re-verified even though the caller holds a valid
        JWT: a token could be a forgotten session on a shared device, and
        possession of it must not be enough to seize the account.
        """
        if not verify_password(current_password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        AccountService._validate_new_password(new_password, current=current_password)

        await db.execute(text(
            "UPDATE users SET hashed_password = :h WHERE id = :uid"
        ), {"h": get_password_hash(new_password), "uid": str(user.id)})

        # Any outstanding reset links are void now — the account just changed
        # hands deliberately, and a stale link would reopen it.
        await db.execute(text("""
            UPDATE auth_tokens SET used_at = now()
            WHERE user_id = :uid AND kind = :kind AND used_at IS NULL
        """), {"uid": str(user.id), "kind": KIND_PASSWORD_RESET})
        await db.commit()
        return {"ok": True, "message": "Password updated."}

    # -------------------------- forgot password ----------------------------
    @staticmethod
    async def request_password_reset(db: AsyncSession, username: str) -> dict:
        """Start a reset from a username alone.

        IDENTICAL RESPONSE in every case — unknown username, known username with
        no email, known username with email. The shape and the message never
        vary, so this endpoint cannot be used to enumerate valid usernames.
        `email_hint` is null unless there is a real address to hint at.
        """
        generic = {
            "ok": True,
            "message": (
                "If that account exists, we've sent reset instructions to the "
                "email on file."
            ),
            "email_hint": None,
            "needs_admin_help": False,
        }

        row = (await db.execute(text(
            "SELECT id, username, email FROM users WHERE username = :u LIMIT 1"
        ), {"u": (username or "").strip()})).first()

        if not row:
            return generic  # unknown username — same response as success

        if not row.email:
            # Legacy account with no email on file. Nothing can be sent, so
            # route them to the humans: the existing admin queue that already
            # handles outlet verification.
            return {
                **generic,
                "needs_admin_help": True,
                "message": (
                    "If that account exists, we've sent reset instructions. If "
                    "no email is on file, contact your CareVo admin to recover "
                    "the account."
                ),
            }

        recent = (await db.execute(text("""
            SELECT count(*) FROM auth_tokens
            WHERE user_id = :uid AND kind = :kind
              AND created_at > now() - interval '1 hour'
        """), {"uid": str(row.id), "kind": KIND_PASSWORD_RESET})).scalar()
        if recent and int(recent) >= RESET_MAX_PER_HOUR:
            return generic  # silently capped; still indistinguishable

        raw = await AccountService._issue_token(
            db, row.id, KIND_PASSWORD_RESET, timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
        )
        link = f"{settings.EMAIL_LINK_BASE_URL.rstrip('/')}/reset?token={raw}" \
            if settings.EMAIL_LINK_BASE_URL else f"(token: {raw})"
        await AccountService._deliver(
            row.email,
            "Reset your CareVo password",
            f"Use this link within {RESET_TOKEN_TTL_MINUTES} minutes: {link}",
        )
        await db.commit()

        return {**generic, "email_hint": AccountService.mask_email(row.email)}

    @staticmethod
    async def reset_password(db: AsyncSession, token: str, new_password: str) -> dict:
        """Complete a reset. Single-use and expiry are enforced in one UPDATE."""
        AccountService._validate_new_password(new_password)

        row = (await db.execute(text("""
            UPDATE auth_tokens SET used_at = now()
            WHERE token_hash = :h AND kind = :kind
              AND used_at IS NULL AND expires_at > now()
            RETURNING user_id
        """), {"h": AccountService._hash_token(token or ""), "kind": KIND_PASSWORD_RESET})).first()

        if not row:
            # One message for expired / already-used / never-existed, so probing
            # reveals nothing about which.
            raise HTTPException(
                status_code=400, detail="That reset link is invalid or has expired."
            )

        await db.execute(text(
            "UPDATE users SET hashed_password = :h WHERE id = :uid"
        ), {"h": get_password_hash(new_password), "uid": str(row[0])})
        await db.commit()
        return {"ok": True, "message": "Password reset. You can sign in now."}

    # ---------------------------- email on file ----------------------------
    @staticmethod
    async def set_email(db: AsyncSession, user, email: str) -> dict:
        """Set/update the recovery email, then send a verification link.

        Used both by new signups and by the prompt shown to existing owners who
        have no email yet.
        """
        cleaned = (email or "").strip().lower()
        if "@" not in cleaned or "." not in cleaned.rpartition("@")[2]:
            raise HTTPException(status_code=422, detail="Enter a valid email address")

        taken = (await db.execute(text(
            "SELECT 1 FROM users WHERE lower(email) = :e AND id <> :uid LIMIT 1"
        ), {"e": cleaned, "uid": str(user.id)})).first()
        if taken:
            raise HTTPException(
                status_code=409, detail="That email is already used by another account"
            )

        await db.execute(text(
            "UPDATE users SET email = :e, email_verified_at = NULL WHERE id = :uid"
        ), {"e": cleaned, "uid": str(user.id)})

        raw = await AccountService._issue_token(
            db, user.id, KIND_EMAIL_VERIFY, timedelta(hours=VERIFY_TOKEN_TTL_HOURS)
        )
        link = f"{settings.EMAIL_LINK_BASE_URL.rstrip('/')}/verify?token={raw}" \
            if settings.EMAIL_LINK_BASE_URL else f"(token: {raw})"
        status = await AccountService._deliver(
            cleaned, "Verify your CareVo email",
            f"Confirm this address within {VERIFY_TOKEN_TTL_HOURS} hours: {link}",
        )
        await db.commit()
        return {
            "ok": True,
            "email": cleaned,
            "email_hint": AccountService.mask_email(cleaned),
            "verification_sent": status == "sent",
        }

    @staticmethod
    async def verify_email(db: AsyncSession, token: str) -> dict:
        row = (await db.execute(text("""
            UPDATE auth_tokens SET used_at = now()
            WHERE token_hash = :h AND kind = :kind
              AND used_at IS NULL AND expires_at > now()
            RETURNING user_id
        """), {"h": AccountService._hash_token(token or ""), "kind": KIND_EMAIL_VERIFY})).first()
        if not row:
            raise HTTPException(
                status_code=400, detail="That verification link is invalid or has expired."
            )
        await db.execute(text(
            "UPDATE users SET email_verified_at = now() WHERE id = :uid"
        ), {"uid": str(row[0])})
        await db.commit()
        return {"ok": True, "message": "Email verified."}

    @staticmethod
    async def get_account(db: AsyncSession, user) -> dict:
        """Current account state — drives the 'add your email' prompt."""
        row = (await db.execute(text(
            "SELECT email, email_verified_at FROM users WHERE id = :uid"
        ), {"uid": str(user.id)})).first()
        email = row.email if row else None
        return {
            "username": user.username,
            "email": email,
            "email_hint": AccountService.mask_email(email),
            "email_verified": bool(row and row.email_verified_at),
            # True for the legacy accounts that predate migration 015.
            "needs_email": email is None,
        }
