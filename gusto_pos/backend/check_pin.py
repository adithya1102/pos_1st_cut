"""
Diagnostic: check users table for PIN-login-eligible accounts.
If empty, creates a default Admin user with PIN 1234.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.modules.users.model import User
from app.modules.roles.model import Role


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.is_active == True))
        users = result.scalars().all()

        if users:
            print(f"\nFound {len(users)} active user(s) in the users table:\n")
            for u in users:
                role_names = [r.name for r in u.roles] if u.roles else ["(no role)"]
                print(f"  id={u.id}  username={u.username!r}  roles={role_names}")
            print(
                "\nPINs are bcrypt-hashed — exact PINs are unknown.\n"
                "Run this script again with --reset to force PIN=1234 on all users,\n"
                "or see below for a new seed user."
            )
            if "--reset" in sys.argv:
                new_hash = get_password_hash("1234")
                for u in users:
                    u.hashed_password = new_hash
                await db.commit()
                print("\nAll users reset to PIN=1234.")
        else:
            print("\nusers table is EMPTY — creating default users...\n")
            pins = [
                ("Admin",  "Owner",  "0000"),
                ("Waiter", "Waiter", "1111"),
            ]
            for username, role_name, pin in pins:
                r = await db.execute(select(Role).where(Role.name == role_name))
                role = r.scalar_one_or_none()
                user = User(
                    username=username,
                    hashed_password=get_password_hash(pin),
                    is_active=True,
                )
                if role:
                    user.roles = [role]
                db.add(user)
                print(f"  CREATED: username={username!r}  role={role_name}  PIN={pin}")

            await db.commit()
            print("\nDone. Use the PINs above to log in.")


if __name__ == "__main__":
    asyncio.run(main())
