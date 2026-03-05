"""Test user creation through the FastAPI test client."""
import asyncio
from app.core.database import AsyncSessionLocal, get_db
from app.modules.users.service import UserService
from app.modules.users.schema import UserCreate, UserRead

async def test():
    async with AsyncSessionLocal() as db:
        try:
            payload = UserCreate(
                username="adithya_owner",
                password="Test@1234",
                outlet_id="cfba2bae-7b19-4a79-ad69-b5cda4a559d2"
            )
            user = await UserService.create_user(db, payload)
            print(f"User created: {user.id}")
            # Now try to serialize with Pydantic
            user_read = UserRead.model_validate(user, from_attributes=True)
            print(f"Serialized: {user_read.model_dump_json()}")
        except Exception as e:
            import traceback
            traceback.print_exc()

asyncio.run(test())
