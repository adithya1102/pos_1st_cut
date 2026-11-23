"""POS registration link: mint/verify/consume a one-time Registration ID that
replaces open sign-up on the Native Gusto POS.

NO SHARED SECRET / HMAC. /pos-link/verify and /pos-link/consume are PUBLIC
endpoints -- a secret baked into a desktop installer is not a secret. The
only protections are: code entropy (CSPRNG, 8 chars from a 32-symbol
alphabet -> ~2^39 space), a 15-minute TTL, single use, and rate limiting.

Rate limiting is two layers, same reasoning as check_register_rate_limit's
own docstring ("single-process; Redis in prod" -- there is no Redis, see
AGENT_GUARDRAILS.md):
  * in-memory per-IP bucket (fast, but forgotten on restart/redeploy), and
  * a DB-backed GLOBAL failure counter (pos_link_rate_limit_state, migration
    044) that survives a restart, counting failures across ALL IPs.
Only FAILED verify/consume calls increment either counter -- a legitimate
POS retrying its own successful flow is never penalised.

Every failure path (unknown code, expired, consumed, revoked, wrong
registration_ref) returns the identical HTTP 400 body so a caller cannot
distinguish one cause from another. No code or registration_ref is ever
logged.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

# 32 symbols, chosen to exclude characters that are easy to mis-type or
# mis-read on a phone screen: no 0/O, 1/I/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
_CODE_LENGTH = 8
_FIXED_TEST_CODE = "1234"

INVALID_CODE_DETAIL = "Code not valid"
_RATE_LIMIT_DETAIL = "Too many attempts, try later"

# Per-IP failure bucket. In-memory, single-process -- see module docstring.
_pos_link_failure_hits: dict[str, list[float]] = defaultdict(list)


def _hash_value(value: str) -> str:
    """SHA-256(value + SECRET_KEY pepper), hex. SECRET_KEY is the one
    server-side secret this app already keeps (JWT signing) -- reused as the
    pepper rather than introducing POS_LINK_SHARED_SECRET, which the
    contract deliberately does not have (a secret in a desktop installer is
    not a secret)."""
    return hashlib.sha256((value + settings.SECRET_KEY).encode()).hexdigest()


def _normalize_code(raw: str) -> str:
    """Strip whitespace/dashes and uppercase, so "wxyz-2345", "WXYZ 2345"
    and "WXYZ2345" all hash identically."""
    return re.sub(r"[\s-]", "", raw or "").strip().upper()


def _format_code(code: str) -> str:
    if len(code) == 8:
        return f"{code[:4]}-{code[4:]}"
    return code


def _generate_code(mode: str) -> str:
    if mode == "fixed-test":
        return _FIXED_TEST_CODE
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class PosLinkService:
    # --------------------------- rate limiting --------------------------
    @staticmethod
    def check_rate_limit(client_ip: str) -> None:
        """Per-IP cap on FAILED attempts. Raises 429 before any DB work."""
        now = time.time()
        window = float(settings.POS_LINK_RATE_LIMIT_WINDOW_SECONDS)
        hits = [t for t in _pos_link_failure_hits[client_ip] if now - t < window]
        _pos_link_failure_hits[client_ip] = hits
        if len(hits) >= settings.POS_LINK_RATE_LIMIT_PER_IP:
            # Until the OLDEST hit falls out of the window -- same
            # reasoning as check_login_rate_limit / check_pickup_miss_limit,
            # which both send this header for the same reason.
            retry_after = max(1, int(window - (now - hits[0])) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=_RATE_LIMIT_DETAIL,
                headers={"Retry-After": str(retry_after)},
            )

    @staticmethod
    def _record_ip_failure(client_ip: str) -> None:
        _pos_link_failure_hits[client_ip].append(time.time())

    @staticmethod
    async def check_global_cooldown(db: AsyncSession) -> None:
        """DB-backed backstop: if the global failure counter already tripped
        a cooldown, refuse before touching anything else."""
        row = (await db.execute(text(
            "SELECT cooldown_until FROM pos_link_rate_limit_state WHERE id = 1"
        ))).first()
        if row is None or row[0] is None:
            return
        cooldown_until = _aware(row[0])
        now = datetime.now(timezone.utc)
        if now < cooldown_until:
            retry_after = max(1, int((cooldown_until - now).total_seconds()) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=_RATE_LIMIT_DETAIL,
                headers={"Retry-After": str(retry_after)},
            )

    @staticmethod
    async def _record_global_failure(db: AsyncSession) -> None:
        now = datetime.now(timezone.utc)
        window = timedelta(seconds=settings.POS_LINK_GLOBAL_FAILURE_WINDOW_SECONDS)
        row = (await db.execute(text(
            "SELECT window_started_at, failure_count FROM pos_link_rate_limit_state "
            "WHERE id = 1 FOR UPDATE"
        ))).first()
        if row is None:
            return
        window_started_at, failure_count = _aware(row[0]), row[1]
        if now - window_started_at > window:
            window_started_at, failure_count = now, 0
        failure_count += 1
        cooldown_until = None
        if failure_count >= settings.POS_LINK_GLOBAL_FAILURE_LIMIT:
            cooldown_until = now + timedelta(
                seconds=settings.POS_LINK_GLOBAL_COOLDOWN_SECONDS
            )
            failure_count, window_started_at = 0, now
        await db.execute(text(
            "UPDATE pos_link_rate_limit_state "
            "SET window_started_at = :w, failure_count = :f, cooldown_until = :c "
            "WHERE id = 1"),
            {"w": window_started_at, "f": failure_count, "c": cooldown_until})
        await db.commit()

    @staticmethod
    async def _fail(db: AsyncSession, client_ip: str) -> None:
        """Record the failure on BOTH counters, then raise the one generic
        body every invalid/expired/used/revoked code gets."""
        PosLinkService._record_ip_failure(client_ip)
        await PosLinkService._record_global_failure(db)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                             detail=INVALID_CODE_DETAIL)

    # --------------------------- mint (owner auth) -----------------------
    @staticmethod
    async def mint_code(db: AsyncSession, outlet_id: str | None) -> dict:
        if not outlet_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This account has no outlet to register.",
            )
        row = (await db.execute(text(
            "SELECT verification_status FROM outlets WHERE id = :o"),
            {"o": outlet_id})).first()
        if row is None or row[0] != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This outlet has not been approved yet.",
            )

        mode = (settings.POS_REG_MODE or "random").strip().lower()
        mode = "fixed-test" if mode == "fixed-test" else "random"
        now = datetime.now(timezone.utc)
        # "TTL ignored" for fixed-test: a far-future expiry rather than a
        # separate no-expiry code path, so every other check (the `now >
        # expires_at` comparison in verify/consume) stays the same shape.
        expires_at = (
            now + timedelta(days=36500) if mode == "fixed-test"
            else now + timedelta(minutes=settings.POS_REG_CODE_TTL_MINUTES)
        )

        # "the server mints a NEW Registration ID every time that screen is
        # opened and revokes any earlier unused ID for that outlet."
        await db.execute(text(
            "UPDATE pos_registration_codes SET revoked_at = :now "
            "WHERE outlet_id = :o AND consumed_at IS NULL AND revoked_at IS NULL"),
            {"now": now, "o": outlet_id})

        code = _generate_code(mode)
        await db.execute(text(
            "INSERT INTO pos_registration_codes "
            "(id, outlet_id, code_hash, mode, created_at, expires_at) "
            "VALUES (gen_random_uuid(), :o, :h, :m, :now, :exp)"),
            {"o": outlet_id, "h": _hash_value(code), "m": mode,
             "now": now, "exp": expires_at})
        await db.commit()
        return {"code": _format_code(code), "expires_at": expires_at}

    # --------------------------- verify (public) -------------------------
    @staticmethod
    async def verify(db: AsyncSession, raw_code: str, client_ip: str) -> dict:
        PosLinkService.check_rate_limit(client_ip)
        await PosLinkService.check_global_cooldown(db)

        code_hash = _hash_value(_normalize_code(raw_code))
        row = (await db.execute(text(
            "SELECT pr.id, pr.outlet_id, pr.mode, pr.expires_at, pr.consumed_at, "
            "       pr.revoked_at, o.location_name, o.locality, o.city, "
            "       o.phone_number, u.username, u.email "
            "FROM pos_registration_codes pr "
            "JOIN outlets o ON o.id = pr.outlet_id "
            "LEFT JOIN users u ON u.outlet_id = pr.outlet_id "
            "                 AND u.is_outlet_owner = true "
            "WHERE pr.code_hash = :h "
            "ORDER BY pr.created_at DESC LIMIT 1"),
            {"h": code_hash})).first()

        if row is None:
            await PosLinkService._fail(db, client_ip)

        (reg_id, outlet_id, mode, expires_at, consumed_at, revoked_at,
         location_name, locality, city, phone, username, email) = row

        if revoked_at is not None:
            await PosLinkService._fail(db, client_ip)
        if mode != "fixed-test" and consumed_at is not None:
            await PosLinkService._fail(db, client_ip)
        if mode != "fixed-test" and datetime.now(timezone.utc) > _aware(expires_at):
            await PosLinkService._fail(db, client_ip)

        registration_ref = secrets.token_urlsafe(32)
        await db.execute(text(
            "UPDATE pos_registration_codes SET registration_ref_hash = :r "
            "WHERE id = :i"),
            {"r": _hash_value(registration_ref), "i": reg_id})
        await db.commit()

        return {
            "registration_ref": registration_ref,
            "outlet": {
                "outlet_id": str(outlet_id),
                "name": location_name,
                "locality": locality,
                "city": city,
            },
            "owner": {
                "name": username or "",
                "email": email,
                "phone": phone,
            },
        }

    # --------------------------- consume (public) -------------------------
    @staticmethod
    async def consume(
        db: AsyncSession, registration_ref: str, pos_install_id: str, client_ip: str
    ) -> dict:
        PosLinkService.check_rate_limit(client_ip)
        await PosLinkService.check_global_cooldown(db)

        row = (await db.execute(text(
            "SELECT id, outlet_id, mode, expires_at, consumed_at, revoked_at, "
            "       pos_install_id "
            "FROM pos_registration_codes WHERE registration_ref_hash = :r"),
            {"r": _hash_value(registration_ref)})).first()

        if row is None:
            await PosLinkService._fail(db, client_ip)

        (reg_id, outlet_id, mode, expires_at, consumed_at, revoked_at,
         existing_install) = row

        if revoked_at is not None:
            await PosLinkService._fail(db, client_ip)
        if mode != "fixed-test" and datetime.now(timezone.utc) > _aware(expires_at):
            await PosLinkService._fail(db, client_ip)

        if mode != "fixed-test" and consumed_at is not None:
            # Idempotent for the SAME install only. A different install
            # trying to consume an already-used code is a reuse attempt and
            # gets the same generic failure as everything else.
            if existing_install == pos_install_id:
                registered_at = (await db.execute(text(
                    "SELECT pos_registered_at FROM outlets WHERE id = :o"),
                    {"o": outlet_id})).scalar()
                return {"outlet_id": str(outlet_id), "pos_registered_at": registered_at}
            await PosLinkService._fail(db, client_ip)

        now = datetime.now(timezone.utc)
        if mode == "fixed-test":
            # Reusable: record the latest install, never consume.
            await db.execute(text(
                "UPDATE pos_registration_codes SET pos_install_id = :p WHERE id = :i"),
                {"p": pos_install_id, "i": reg_id})
        else:
            await db.execute(text(
                "UPDATE pos_registration_codes "
                "SET consumed_at = :now, pos_install_id = :p WHERE id = :i"),
                {"now": now, "p": pos_install_id, "i": reg_id})

        await db.execute(text(
            "UPDATE outlets SET pos_registered_at = :now WHERE id = :o"),
            {"now": now, "o": outlet_id})
        await db.commit()

        return {"outlet_id": str(outlet_id), "pos_registered_at": now}
