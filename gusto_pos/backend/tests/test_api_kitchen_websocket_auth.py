"""The kitchen-display WebSocket is authenticated and outlet-scoped.

/ws/kitchen/{outlet_id} previously accepted ANY connection for ANY outlet id
with no credential at all. It streams every NEW_ORDER and every status change
for the outlet and accepts messages back, so an unauthenticated listener could
watch a restaurant's entire live order flow — and an authenticated staff member
at one outlet could watch another outlet in the same deployment.

The sibling socket /ws/order/{order_id} was closed in an earlier pass
(test_api_order_websocket_auth.py); this one was left open. Same close codes
deliberately, so a client treats both refusals the same way:
  4401 — no token, a malformed token, a customer token, or an unknown/inactive
         staff subject
  4403 — valid staff, but not this outlet (or a malformed outlet id)

A mismatched outlet and a malformed outlet id are answered identically, so the
socket cannot be used to probe which outlets exist.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.main import app
from app.modules.carevo_customer.deps import create_customer_token

WS_UNAUTHENTICATED = 4401
WS_NOT_YOUR_OUTLET = 4403


async def _drive_ws(outlet_id, token=None, client_messages=()):
    """Run the ASGI websocket endpoint on the CURRENT event loop.

    Starlette's TestClient is deliberately avoided for the reason spelled out
    in test_api_order_websocket_auth.py: it runs the app in its own event loop
    via a portal, and this suite pins ONE session-scoped loop (pytest.ini)
    because the app's SQLAlchemy engine is a module-level singleton whose
    pooled connections belong to that loop.

    Returns the list of ASGI messages the app sent.
    """
    path = f"/ws/kitchen/{outlet_id}"
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


async def _expect_refusal(outlet_id, token, expected_code):
    """The socket must be CLOSED, never accepted."""
    sent = await _drive_ws(outlet_id, token)
    kinds = [m["type"] for m in sent]
    assert "websocket.accept" not in kinds, \
        f"the socket was accepted — it should have been refused ({kinds})"
    closes = [m for m in sent if m["type"] == "websocket.close"]
    assert closes, f"the socket was neither accepted nor closed: {sent}"
    assert closes[0].get("code") == expected_code, (
        f"closed with {closes[0].get('code')}, expected {expected_code}")


@pytest.mark.asyncio
async def test_no_token_is_refused(seed):
    """The whole point: this used to be an open socket."""
    await _expect_refusal(seed["outlet_id"], None, WS_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_garbage_token_is_refused(seed):
    await _expect_refusal(seed["outlet_id"], "not-a-jwt", WS_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_a_customer_token_cannot_open_a_kitchen_socket(seed, db):
    """`typ` separates the two token families; a customer is not staff.

    A customer must never see an outlet's whole order flow, which is exactly
    what this socket streams.
    """
    cid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO customers (id, phone_number, name, points_balance, "
             "created_at) VALUES (:i, :p, :n, 0, now())"),
        {"i": str(cid), "p": f"+9187{uuid.uuid4().hex[:8]}", "n": "A Customer"})
    await db.commit()
    await _expect_refusal(
        seed["outlet_id"], create_customer_token(str(cid)), WS_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_an_unknown_subject_is_refused(seed):
    """A correctly SIGNED token whose subject is nobody.

    The signature is valid, so this only fails if the user row is actually
    looked up rather than the token being trusted on its own.
    """
    await _expect_refusal(
        seed["outlet_id"],
        create_access_token(subject=f"ghost_{uuid.uuid4().hex[:8]}"),
        WS_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_a_deactivated_staff_member_is_refused(seed, db):
    """is_active is the off-switch for a departed employee; a live token must
    stop working the moment it is thrown."""
    tag = uuid.uuid4().hex[:8]
    uid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i, :u, 'x', false, :o, now())"""),
        {"i": str(uid), "u": f"gone_{tag}", "o": seed["outlet_id"]})
    await db.commit()
    await _expect_refusal(
        seed["outlet_id"], create_access_token(subject=f"gone_{tag}"),
        WS_UNAUTHENTICATED)


@pytest.mark.asyncio
async def test_another_outlets_staff_is_refused(seed, db):
    """THE cross-outlet leak: real, valid, active staff — wrong outlet."""
    tag = uuid.uuid4().hex[:8]
    org_id, other_outlet, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(
        text("INSERT INTO organizations (id, name, created_at) "
             "VALUES (:i, :n, now())"),
        {"i": str(org_id), "n": f"TEST_CAREVO_kitchen_org_{tag}"})
    # geofence_radius_meters and verification_status are NOT NULL with no
    # server default — the ORM fills them in Python, so raw SQL must supply
    # them. Same shape as the seed fixture in conftest.
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city,
                             is_visible, upi_id, geofence_radius_meters,
                             verification_status, created_at)
        VALUES (:i, :o, :n, 'Testville', true, 'test@upi', 150, 'active', now())"""),
        {"i": str(other_outlet), "o": str(org_id),
         "n": f"TEST_CAREVO_kitchen_other_{tag}"})
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i, :u, 'x', true, :o, now())"""),
        {"i": str(uid), "u": f"other_{tag}", "o": str(other_outlet)})
    await db.commit()

    await _expect_refusal(
        seed["outlet_id"], create_access_token(subject=f"other_{tag}"),
        WS_NOT_YOUR_OUTLET)


@pytest.mark.asyncio
async def test_staff_with_no_outlet_is_refused(seed, db):
    """outlet_id is nullable; a staff row without one is scoped to nothing and
    must not fall through to 'matches everything'."""
    tag = uuid.uuid4().hex[:8]
    uid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i, :u, 'x', true, NULL, now())"""),
        {"i": str(uid), "u": f"floating_{tag}"})
    await db.commit()
    await _expect_refusal(
        seed["outlet_id"], create_access_token(subject=f"floating_{tag}"),
        WS_NOT_YOUR_OUTLET)


@pytest.mark.asyncio
async def test_a_non_uuid_outlet_id_is_refused_not_a_500(seed):
    """outlet_id comes off the wire; a malformed one must not reach asyncpg."""
    await _expect_refusal(
        "not-a-uuid", create_access_token(subject=seed["owner_username"]),
        WS_NOT_YOUR_OUTLET)


@pytest.mark.asyncio
async def test_the_outlets_own_staff_can_still_connect(seed):
    """The guard must not break the feature it protects.

    Proves the socket still accepts, still reaches the connection manager, and
    still answers a message — the kitchen display's whole contract.
    """
    token = create_access_token(subject=seed["owner_username"])
    sent = await _drive_ws(seed["outlet_id"], token, client_messages=["ready 7"])
    kinds = [m["type"] for m in sent]
    assert "websocket.accept" in kinds, f"the outlet's own staff was refused: {sent}"

    texts = [m["text"] for m in sent
             if m["type"] == "websocket.send" and "text" in m]
    assert any(t == "ACK: ready 7" for t in texts), \
        f"the socket accepted but did not acknowledge a message: {texts}"


@pytest.mark.asyncio
async def test_a_user_id_subject_also_works(seed, db):
    """Pin login mints a user ID as the subject, password login a username.

    Both have to open this socket, which is why _authorize resolves the subject
    two ways — a regression here would lock out exactly one of the two login
    routes, silently.
    """
    row = (await db.execute(
        text("SELECT id FROM users WHERE username = :u"),
        {"u": seed["owner_username"]})).first()
    token = create_access_token(subject=str(row[0]))
    sent = await _drive_ws(seed["outlet_id"], token)
    assert "websocket.accept" in [m["type"] for m in sent], \
        f"a user-id subject was refused: {sent}"
