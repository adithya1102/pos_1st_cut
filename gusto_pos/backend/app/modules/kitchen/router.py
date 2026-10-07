from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decode_access_token
from app.core.database import get_db
from app.core.websocket_manager import kitchen_manager
from app.modules.users.model import User
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Kitchen Display"])

# Close codes, matching /ws/order/{order_id} so a client can treat the two
# sockets' refusals identically. 1008 is RFC 6455 "policy violation"; the 4xxx
# range is application-defined and is what lets the two refusals be told apart.
WS_UNAUTHENTICATED = 4401
WS_NOT_YOUR_OUTLET = 4403


async def _authorize(websocket: WebSocket, outlet_id: str, db: AsyncSession) -> bool:
    """Is the caller active staff AT THIS OUTLET?

    The token arrives as a QUERY PARAMETER, not an Authorization header,
    because the browser WebSocket API cannot set request headers — the kitchen
    display is a web page (`app/static/kitchen.html`), so there is no portable
    header channel on the handshake. The URL is wss:// in production, so the
    token is inside TLS; the real cost is that it can land in access logs,
    which is why it is the ordinary short-lived staff token and not a secret
    of its own.

    STAFF, not customer: `typ` separates the two token families (see
    carevo_customer/deps.py), and a customer token must not open a socket that
    streams an outlet's entire order flow. Subject resolution mirrors
    get_current_staff — the subject may be a username or a user id, because
    password login and pin login mint different subjects.

    Returns True when the socket may proceed. On refusal it closes the socket
    with a distinguishing code and returns False.
    """
    token = websocket.query_params.get("token") or ""
    if not token:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False

    try:
        payload = decode_access_token(token)
    except JWTError:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False

    # A customer token is not staff. Rejected on `typ` rather than on whether
    # the subject happens to match a user row, so a customer whose id collided
    # with a username could never slip through.
    if payload.get("typ") == "customer":
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False

    sub = payload.get("sub")
    if not sub:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False

    conditions = [User.username == sub]
    # The subject might be a UUID (pin-login), so match on id too when it
    # parses. Same two-way lookup as get_current_staff.
    try:
        conditions.append(User.id == uuid.UUID(str(sub)))
    except (ValueError, AttributeError, TypeError):
        pass

    try:
        user = (await db.execute(select(User).where(or_(*conditions)))).scalars().first()
    except Exception:
        await db.rollback()
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False

    if not user or not user.is_active:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False

    # Outlet scoping. A valid token for outlet A must not stream outlet B's
    # orders — this socket carries every NEW_ORDER at the outlet, so without
    # this any authenticated staff member anywhere could watch a competitor
    # outlet in the same deployment.
    #
    # A malformed outlet_id off the wire and a mismatched one are answered
    # identically, so the socket cannot be used to probe which outlets exist.
    try:
        requested = uuid.UUID(str(outlet_id))
    except (ValueError, AttributeError, TypeError):
        await websocket.close(code=WS_NOT_YOUR_OUTLET)
        return False

    if not user.outlet_id or user.outlet_id != requested:
        await websocket.close(code=WS_NOT_YOUR_OUTLET)
        return False

    return True


@router.websocket("/ws/kitchen/{outlet_id}")
async def kitchen_websocket(
    websocket: WebSocket,
    outlet_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Kitchen display connects here.
    URL: wss://<host>/ws/kitchen/{outlet_id}?token=<staff JWT>

    AUTHENTICATED AND OUTLET-SCOPED. This socket previously accepted any
    connection for any outlet id with no credential at all. It streams every
    new order and every status change for the outlet, and accepts messages
    back, so an unauthenticated listener could watch a restaurant's entire
    order flow in real time.

    It then receives real-time events:
    - NEW_ORDER: when a waiter submits a new order
    - ORDER_STATUS_UPDATED: when status changes
    """
    # Authorise BEFORE accept, so a rejected handshake never becomes an open
    # socket and never reaches the connection manager.
    if not await _authorize(websocket, outlet_id, db):
        logger.info("Rejected kitchen WS for outlet %s", outlet_id)
        return

    await kitchen_manager.connect(websocket, outlet_id)
    logger.info(f"Kitchen screen connected for outlet {outlet_id}")

    try:
        while True:
            # Kitchen can also send messages (e.g. mark order as ready)
            data = await websocket.receive_text()
            logger.info(f"Message from kitchen [{outlet_id}]: {data}")
            # Echo back as acknowledgement
            await websocket.send_text(f"ACK: {data}")

    except WebSocketDisconnect:
        kitchen_manager.disconnect(websocket, outlet_id)
        logger.info(f"Kitchen screen disconnected from outlet {outlet_id}")
