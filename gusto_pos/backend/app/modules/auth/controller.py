from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import create_access_token
from app.core.security import verify_password
from app.modules.users.model import User
from app.modules.users.schema import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token")
async def login(username: str, password: str, db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(User).where(User.username == username))
    user = q.scalars().first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(subject=str(user.id))
    return {"access_token": token, "token_type": "bearer"}
