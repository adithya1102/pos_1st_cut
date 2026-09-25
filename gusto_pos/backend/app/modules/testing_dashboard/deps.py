"""Shared-secret gate for every testing-dashboard endpoint.

The key lives ONLY in the environment (TESTING_DASHBOARD_KEY), never in source.
FAIL-CLOSED: if the key is unset (empty), every request is rejected — the
dashboard does not accidentally become open because someone forgot to set it.
A missing or wrong header gets a plain 401 and touches nothing else.
"""
import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_testing_key(x_testing_key: str | None = Header(default=None)):
    key = settings.TESTING_DASHBOARD_KEY
    # compare_digest, not `!=`: a plain string comparison returns as soon as it
    # finds a differing byte, so the time it takes leaks how much of the key
    # was guessed correctly. That turns a search over the whole keyspace into
    # a per-character one. The fail-closed check on `key` stays first and short
    # -circuits, which is fine — an unset key is not a secret to protect.
    if not key or not hmac.compare_digest(x_testing_key or "", key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing testing key",
        )
