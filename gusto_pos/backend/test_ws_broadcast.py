"""Test WebSocket broadcast: new order + status update."""
import asyncio
import websockets
import json
import httpx

OUTLET_ID = "0b8a8349-6144-41a8-b028-b9089bd8eaea"
WS_URL = f"ws://127.0.0.1:8000/ws/kitchen/{OUTLET_ID}"
API_URL = "http://127.0.0.1:8000/api/v1"


async def test_new_order_broadcast():
    """Test 1: Create order and verify kitchen receives broadcast."""
    received = []

    async def listen(ws, stop_event):
        try:
            while not stop_event.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    received.append(json.loads(msg))
                    print(f"  Kitchen received: {msg}")
                except asyncio.TimeoutError:
                    continue
        except Exception:
            pass

    print("=" * 50)
    print("TEST 1: New Order Broadcast")
    print("=" * 50)
    print("Connecting kitchen display...")
    async with websockets.connect(WS_URL) as ws:
        print("Kitchen display: CONNECTED")
        stop_event = asyncio.Event()
        listener = asyncio.create_task(listen(ws, stop_event))
        await asyncio.sleep(1)

        print("Creating new order...")
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{API_URL}/orders/", json={
                "outlet_id": OUTLET_ID,
                "total_amount": 350.00
            })
            if r.status_code in [200, 201]:
                order = r.json()
                order_id = order["id"]
                print(f"Order created: {order_id}")
            else:
                print(f"Order creation failed: {r.status_code} {r.text}")
                stop_event.set()
                return None

        print("Waiting for broadcast...")
        await asyncio.sleep(3)
        stop_event.set()
        await listener

        if received:
            for msg in received:
                if msg.get("event") == "NEW_ORDER":
                    print("BROADCAST TEST: PASSED")
                    print(f"  Event: {msg['event']}")
                    print(f"  Order ID: {msg.get('order_id')}")
                    print(f"  Kitchen Token: {msg.get('kitchen_token')}")
                    print(f"  Status: {msg.get('order_status')}")
                    return order_id
        else:
            print("BROADCAST TEST: FAILED - No messages received")
            return order_id if 'order_id' in dir() else None


async def test_status_update_broadcast(order_id: str):
    """Test 2: Update order status and verify kitchen receives broadcast."""
    received = []

    print()
    print("=" * 50)
    print("TEST 2: Status Update Broadcast")
    print("=" * 50)

    if not order_id:
        # Get latest order
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_URL}/orders/")
            orders = r.json()
            if not orders:
                print("No orders found")
                return
            order_id = orders[0]["id"] if isinstance(orders, list) else orders["items"][0]["id"]
    print(f"Using order: {order_id}")

    async with websockets.connect(WS_URL) as ws:
        print("Connected to kitchen display")

        async def listen():
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                received.append(json.loads(msg))
                print(f"  Received: {msg}")
            except asyncio.TimeoutError:
                print("  No message received in 5s")

        listener = asyncio.create_task(listen())
        await asyncio.sleep(0.5)

        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"{API_URL}/orders/{order_id}",
                json={"order_status": "in_kitchen"}
            )
            print(f"Status update response: {r.status_code}")

        await listener

        if received and received[0].get("event") == "ORDER_STATUS_UPDATED":
            print("STATUS BROADCAST: PASSED")
            print(f"  Event: {received[0]['event']}")
            print(f"  Order ID: {received[0].get('order_id')}")
            print(f"  Status: {received[0].get('order_status')}")
        else:
            print("STATUS BROADCAST: FAILED")


async def main():
    order_id = await test_new_order_broadcast()
    await test_status_update_broadcast(order_id)
    print()
    print("=" * 50)
    print("ALL TESTS COMPLETE")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
