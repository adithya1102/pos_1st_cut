from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.modules.users.model import User
from app.core.security import verify_password
from app.core.auth import create_access_token

class AuthService:
    @staticmethod
    async def authenticate_user(db: AsyncSession, username: str, password: str):
        # 1. Fetch user from DB
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalars().first()
        
        # 2. Verify existence and password
        if not user or not verify_password(password, user.hashed_password):
            return None
            
        # 3. Create token
        access_token = create_access_token(subject=user.username)
        return {"access_token": access_token, "token_type": "bearer"}