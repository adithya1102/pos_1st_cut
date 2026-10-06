"""The order-tracking WebSocket is authenticated and ownership-scoped.

/ws/order/{order_id} previously accepted ANY connection for ANY order id with
no credential. Order ids are UUIDs, but they are not secrets — they are handed
to the customer in a URL, pasted into chats, and appear in screenshots. The
socket streams live order events and accepts `request_bill` and `cancel_order`
on the customer's behalf, so anyone holding an id could watch someone else's
order and act on it.

Two refusals, told apart by close code so the client can react differently:
  4401 — no token, a malformed token, or a staff token
  4403 — a valid customer token for somebody else's order (or no such order)

Unknown order and someone else's order are deliberately indistinguishable, so
the socket cannot be used to probe which ids exist.
"""
import asyncio
import json
import uuid

import pytest

from app.core.auth import create_access_token
from app.main import app
from app.modules.carevo_customer.deps import create_customer_token
from tests.conftest import API

WS_UNAUTHENTICATED = 4401
WS_NOT_YOUR_ORDER = 4403


async def _drive_ws(order_id, token=None, client_messages=()):
    """Run the ASGI websocket endpoint on the CURRENT event loop.

    Starlette's TestClient is deliberately avoided. It runs the app in its own
    event loop via a portal, and this suite pins one session-scoped loop
    (pytest.ini) because the app's SQLAlchemy engine is a module-level
    singleton whose pooled connections belong to that loop. Driving the app
    through TestClient produces exactly the failure conftest.py warns about:
    "connection was closed in the middle of operation".

    Returns the list of ASGI messages the app sent.
    """
    path = f"/ws/order/{order_id}"
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": f"token={token}".encode() if token else b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "subprotocols": [],
        "state": {},
    }

    inbound = asyncio.Queue()
    inbound.put_nowait({"type": "websocket.connect"})
    for msg in client_messages:
        inbound.put_nowait({"type": "websocket.receive", "text": msg})
    # Always terminate, so an ACCEPTED socket's receive loop cannot hang the
    # test waiting for input that never comes.
    inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})

    sent = []

    async def receive():
        return await inbound.get()

    async def send(message):
        sent.append(message)

    await asyncio.wait_for(app(scope, receive, send), timeout=15)
    return sent


async def _expect_refusal(order_id, token, expected_code):
    """The socket must be CLOSED, never accepted."""
    sent = await _drive_ws(order_id, token)
    kinds = [m["type"] for m in sent]
    assert "websocket.accept" not in kinds, \
        f"the socket was accepted — it should have been refused ({kinds})"
    closes = [m for m in sent if m["type"] == "websocket.close"]
    assert closes, f"the socket was neither accepted nor closed: {sent}"
    assert closes[0].get("code") == expected_code, (
        f"closed with {closes[0].get('code')}, expected {expected_code}")


@pytest.mark.asyncio
async def test_no_token_is_refused(client, seed):
    r = await client.post(
        f"{API}/customer/orders", headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"],
              "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]})
    order_id = r.json()["id"]
    await _expect_refusal(order_id, None, WS_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_garbage_token_is_refused(client, seed):
    r = await client.post(
        f"{API}/customer/orders", headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"],
              "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]})
    await _expect_refusal(r.json()["id"], "not-a-jwt", WS_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_a_staff_token_cannot_open_a_customer_socket(client, seed):
    """`typ` separates the two token families; a staff JWT is not a customer."""
    r = await client.post(
        f"{API}/customer/orders", headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"],
              "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]})
    staff_token = create_access_token(subject=seed["owner_username"])
    await _expect_refusal(r.json()["id"], staff_token, WS_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_another_customers_token_is_refused(client, seed, db):
    """The actual IDOR: a real, valid customer token for an order that is not
    theirs."""
    r = await client.post(
        f"{API}/customer/orders", headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"],
              "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]})
    order_id = r.json()["id"]

    from sqlalchemy import text
    other_id = uuid.uuid4()
    await db.execute(
        text("INSERT INTO customers (id, phone_number, name, points_balance, "
             "created_at) VALUES (:i, :p, :n, 0, now())"),
        {"i": str(other_id), "p": f"+9188{uuid.uuid4().hex[:8]}", "n": "Someone Else"})
    await db.commit()

    await _expect_refusal(order_id, create_customer_token(str(other_id)), WS_NOT_YOUR_ORDER)


@pytest.mark.asyncio
async def test_unknown_order_is_refused_the_same_way(client, seed):
    """Indistinguishable from someone else's order, so ids cannot be probed."""
    token = seed["customer_auth"]["Authorization"].split(" ", 1)[1]
    await _expect_refusal(str(uuid.uuid4()), token, WS_NOT_YOUR_ORDER)


@pytest.mark.asyncio
async def test_a_non_uuid_order_id_is_refused_not_a_500(client, seed):
    """order_id comes off the wire; a malformed one must not reach asyncpg."""
    token = seed["customer_auth"]["Authorization"].split(" ", 1)[1]
    await _expect_refusal("not-a-uuid", token, WS_NOT_YOUR_ORDER)


@pytest.mark.asyncio
async def test_the_owner_can_still_connect(client, seed):
    """The guard must not break the feature it protects."""
    r = await client.post(
        f"{API}/customer/orders", headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"],
              "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]})
    order_id = r.json()["id"]
    token = seed["customer_auth"]["Authorization"].split(" ", 1)[1]

    sent = await _drive_ws(order_id, token, client_messages=['{"event": "ping"}'])
    kinds = [m["type"] for m in sent]
    assert "websocket.accept" in kinds, f"the owner was refused: {sent}"

    frames = [json.loads(m["text"]) for m in sent
              if m["type"] == "websocket.send" and "text" in m]
    assert frames[0]["event"] == "CONNECTED"
    assert frames[0]["order_id"] == order_id
    assert any(f["event"] == "pong" for f in frames),         f"the socket accepted but did not answer a ping: {frames}"
