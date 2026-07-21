"""Auth token helpers and bearer dependencies for CareVo Skip.

Reuses app.core.auth (jose, SECRET_KEY/ALGORITHM from settings). Customer tokens
carry an extra `"typ": "customer"` claim so staff endpoints can reject them.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.auth import decode_access_token
from app.core.database import get_db
from app.modules.customers.model import Customer
from app.modules.users.model import User

_bearer = HTTPBearer(auto_error=True)


def create_customer_token(customer_id: str, expires_delta: Optional[timedelta] = None) -> str:
    """create_access_token-equivalent that adds a `typ=customer` claim."""
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(customer_id), "typ": "customer", "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_customer(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Customer:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing customer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(creds.credentials)
    except JWTError:
        raise cred_exc
    if payload.get("typ") != "customer":
        raise cred_exc
    sub = payload.get("sub")
    if not sub:
        raise cred_exc
    res = await db.execute(select(Customer).where(Customer.id == sub))
    customer = res.scalars().first()
    if not customer:
        raise cred_exc
    return customer


async def get_current_staff(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Staff bearer: reject customer tokens, then resolve subject against users
    table (subject may be the user id or the username, per existing auth flows)."""
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Staff authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(creds.credentials)
    except JWTError:
        raise cred_exc
    if payload.get("typ") == "customer":
        raise cred_exc
    sub = payload.get("sub")
    if not sub:
        raise cred_exc

    conditions = [User.username == sub]
    # subject might be a UUID (pin-login) — match on id too when it parses.
    try:
        import uuid as _uuid
        conditions.append(User.id == _uuid.UUID(str(sub)))
    except (ValueError, AttributeError, TypeError):
        pass

    res = await db.execute(select(User).where(or_(*conditions)))
    user = res.scalars().first()
    if not user or not user.is_active:
        raise cred_exc
    return user
