from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.modules.users.model import User
from app.core.security import verify_and_rehash
from app.core.auth import create_access_token

class AuthService:
    @staticmethod
    async def authenticate_user(db: AsyncSession, username: str, password: str):
        # 1. Fetch user from DB
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalars().first()
        
        # 2. Verify existence and password
        if not user:
            return None
        ok, new_hash = verify_and_rehash(password, user.hashed_password)
        if not ok:
            return None

        # 2b. Upgrade the stored hash if it is still on the deprecated
        #     algorithm. This is the ONLY point at which that is possible: the
        #     plaintext is not recoverable from the database, so a bcrypt hash
        #     can only be computed while the user is holding it out to us.
        #
        #     Best-effort. A failure to persist the upgrade must never turn a
        #     correct password into a failed login — the user authenticated,
        #     and the old hash still works.
        if new_hash:
            try:
                user.hashed_password = new_hash
                await db.commit()
            except Exception:
                await db.rollback()

        # 3. Create token
        access_token = create_access_token(subject=user.username)
        return {"access_token": access_token, "token_type": "bearer"}