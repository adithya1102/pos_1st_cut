import asyncio
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError

def test():
    req = Request(
        "http://127.0.0.1:8001/api/v1/users/",
        data=json.dumps({
            "username": "adithya_owner2",
            "password": "Test@1234",
            "outlet_id": "cfba2bae-7b19-4a79-ad69-b5cda4a559d2"
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urlopen(req)
        print(f"STATUS: {resp.status}")
        print(f"BODY: {resp.read().decode()}")
    except HTTPError as e:
        print(f"STATUS: {e.code}")
        print(f"BODY: {e.read().decode()}")

test()
