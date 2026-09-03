"""Shared-secret gate for every testing-dashboard endpoint.

The key lives ONLY in the environment (TESTING_DASHBOARD_KEY), never in source.
FAIL-CLOSED: if the key is unset (empty), every request is rejected — the
dashboard does not accidentally become open because someone forgot to set it.
A missing or wrong header gets a plain 401 and touches nothing else.
"""
from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_testing_key(x_testing_key: str | None = Header(default=None)):
    key = settings.TESTING_DASHBOARD_KEY
    if not key or x_testing_key != key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing testing key",
        )
