import asyncio
import websockets
import json
import httpx

OUTLET_ID = "cfba2bae-7b19-4a79-ad69-b5cda4a559d2"
API_URL = "http://127.0.0.1:8000/api/v1"


async def test():
    # Create an order first
    print("Creating order...")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{API_URL}/orders/",
            json={"outlet_id": OUTLET_ID, "total_amount": 450.00},
        )
        print(f"Order response status: {r.status_code}")
        order = r.json()
        ORDER_ID = order["id"]
        print(f"Order: {ORDER_ID}")

    # Connect as customer to track the order
    WS_URL = f"ws://127.0.0.1:8000/ws/order/{ORDER_ID}"
    print(f"Customer connecting to: {WS_URL}")

    received = []

    async with websockets.connect(WS_URL) as ws:
        print("Customer: CONNECTED")

        # Should get CONNECTED event immediately
        welcome = await asyncio.wait_for(ws.recv(), timeout=3.0)
        welcome_msg = json.loads(welcome)
        evt = welcome_msg["event"]
        print(f"Welcome: {evt}")
        received.append(welcome_msg)

        # Now update order status and check customer gets notified
        print("Updating order status to in_kitchen...")
        async with httpx.AsyncClient() as client:
            r2 = await client.put(
                f"{API_URL}/orders/{ORDER_ID}",
                json={"order_status": "in_kitchen"},
            )
            print(f"Update response status: {r2.status_code}")

        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            msg_data = json.loads(msg)
            received.append(msg_data)
            evt2 = msg_data["event"]
            print(f"Status update received: {evt2}")
        except asyncio.TimeoutError:
            print("No status update received (timeout)")

    print("")
    print("=== RESULTS ===")
    for m in received:
        evt_name = m["event"]
        detail = m.get("message", m.get("order_status", ""))
        print(f"  {evt_name}: {detail}")

    connected = any(m["event"] == "CONNECTED" for m in received)
    status_update = any(m["event"] == "ORDER_STATUS_CHANGED" for m in received)

    print("")
    if connected:
        print("CUSTOMER WS CONNECT:    PASSED")
    else:
        print("CUSTOMER WS CONNECT:    FAILED")

    if status_update:
        print("CUSTOMER STATUS UPDATE: PASSED")
    else:
        print("CUSTOMER STATUS UPDATE: FAILED")


asyncio.run(test())
