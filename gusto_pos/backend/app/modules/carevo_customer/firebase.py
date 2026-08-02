"""Firebase ID token verification for the CareVo Skip customer login.

Deliberately does NOT use firebase-admin. That SDK needs a service-account JSON
held as a deploy secret; verifying an ID token only needs Google's *public*
signing keys, so this module fetches those instead and keeps the deploy
secret-free — FIREBASE_PROJECT_ID is the only configuration.

Keys are published as JWKs (not X.509) at the endpoint below, which python-jose
consumes directly; the sibling x509 endpoint would need a cert parser.
Google rotates them roughly daily and advertises the lifetime via Cache-Control,
which is honoured here.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx
from fastapi import HTTPException
from jose import jwt, JWTError

from app.core.config import settings

_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)

# Cached JWKS: {kid: jwk_dict}, with the epoch second the cache goes stale.
_jwks_cache: dict[str, dict[str, Any]] = {}
_jwks_expires_at: float = 0.0

# Used only when Google's response carries no usable Cache-Control max-age.
_FALLBACK_TTL_SECONDS = 3600


def _auth_error(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


async def _fetch_jwks(force: bool = False) -> dict[str, dict[str, Any]]:
    """Return {kid: jwk}, refreshing from Google when the cache is stale."""
    global _jwks_cache, _jwks_expires_at

    if not force and _jwks_cache and time.time() < _jwks_expires_at:
        return _jwks_cache

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(_JWKS_URL)
            res.raise_for_status()
            data = res.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Serve stale keys rather than locking every customer out on a blip.
        if _jwks_cache:
            return _jwks_cache
        raise HTTPException(
            status_code=503,
            detail="Unable to reach Firebase key server",
        ) from exc

    keys = {k["kid"]: k for k in data.get("keys", []) if k.get("kid")}
    if not keys:
        if _jwks_cache:
            return _jwks_cache
        raise HTTPException(status_code=503, detail="Firebase key server returned no keys")

    ttl = _FALLBACK_TTL_SECONDS
    cache_control = res.headers.get("cache-control", "")
    for part in cache_control.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                ttl = max(int(part.split("=", 1)[1]), 60)
            except ValueError:
                pass
            break

    _jwks_cache = keys
    _jwks_expires_at = time.time() + ttl
    return _jwks_cache


async def verify_id_token(id_token: str) -> dict[str, Any]:
    """Verify a Firebase ID token and return its claims.

    Raises 401 for anything untrustworthy, 503 if Google is unreachable and no
    cached key works.
    """
    project_id = settings.FIREBASE_PROJECT_ID
    if not project_id:
        raise HTTPException(
            status_code=500,
            detail="FIREBASE_PROJECT_ID is not configured on this deployment",
        )

    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise _auth_error("Malformed Firebase token") from exc

    if header.get("alg") != "RS256":
        # Guards against a token signed with `none` or an HMAC alg.
        raise _auth_error("Unexpected Firebase token algorithm")

    kid = header.get("kid")
    if not kid:
        raise _auth_error("Firebase token has no key id")

    jwks = await _fetch_jwks()
    key = jwks.get(kid)
    if key is None:
        # Unknown kid usually means rotation outran the cache — refetch once.
        jwks = await _fetch_jwks(force=True)
        key = jwks.get(kid)
    if key is None:
        raise _auth_error("Firebase token signed with an unknown key")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"https://securetoken.google.com/{project_id}",
        )
    except JWTError as exc:
        # jose covers signature, exp, aud and iss.
        raise _auth_error(f"Invalid Firebase token: {exc}") from exc

    # `sub` is the Firebase uid; it must be present and non-empty. jose does not
    # check it, and an empty subject would otherwise pass as a valid identity.
    if not claims.get("sub"):
        raise _auth_error("Firebase token has no subject")

    # auth_time in the future means the token is not yet legitimately usable.
    auth_time = claims.get("auth_time")
    if isinstance(auth_time, (int, float)) and auth_time > time.time() + 60:
        raise _auth_error("Firebase token used before its authentication time")

    return claims


async def verify_phone_token(id_token: str) -> tuple[str, str]:
    """Verify a phone-auth ID token. Returns (phone_number, firebase_uid)."""
    claims = await verify_id_token(id_token)

    phone = claims.get("phone_number")
    if not phone:
        # Token is valid but came from a non-phone provider (Google, email, …),
        # which this login path cannot map onto a Customer record.
        raise _auth_error("Firebase token is not a phone-number sign-in")

    return str(phone), str(claims["sub"])


def normalize_phone(phone: str) -> str:
    """Strip formatting so Firebase's E.164 matches stored phone numbers."""
    return "".join(ch for ch in phone if ch.isdigit() or ch == "+").strip()


def find_phone_variants(phone: str) -> list[str]:
    """Candidate spellings of [phone] for matching pre-Firebase customer rows.

    Firebase always returns E.164 (+919876543210); rows created by the stub flow
    may hold a bare local number (9876543210). Matching both keeps a customer's
    order history attached to them after the cutover.
    """
    normalized = normalize_phone(phone)
    variants = [normalized]
    if normalized.startswith("+"):
        digits = normalized[1:]
        variants.append(digits)
        # Indian numbers: also try without the 91 country code.
        if digits.startswith("91") and len(digits) > 10:
            variants.append(digits[2:])
    return list(dict.fromkeys(v for v in variants if v))
