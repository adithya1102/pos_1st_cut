import asyncio
import traceback
from app.core.database import AsyncSessionLocal
from app.modules.users.service import UserService
from app.modules.users.schema import UserCreate

async def test():
    try:
        async with AsyncSessionLocal() as db:
            payload = UserCreate(
                username="test_user_debug",
                password="Test@1234",
                outlet_id="cfba2bae-7b19-4a79-ad69-b5cda4a559d2"
            )
            result = await UserService.create_user(db, payload)
            print("SUCCESS:", result.id, result.username)
    except Exception:
        traceback.print_exc()

asyncio.run(test())
