import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://127.0.0.1:8001/api/v1/users/",
            json={
                "username": "adithya_owner2",
                "password": "Test@1234",
                "outlet_id": "cfba2bae-7b19-4a79-ad69-b5cda4a559d2"
            }
        )
        print(f"STATUS: {r.status_code}")
        print(f"BODY: {r.text}")

asyncio.run(test())
