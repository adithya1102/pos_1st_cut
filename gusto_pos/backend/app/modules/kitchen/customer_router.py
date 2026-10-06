from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decode_access_token
from app.core.database import get_db
from app.core.websocket_manager import customer_manager
import logging
import json

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Customer WebSocket"])

# Close codes. 1008 is the RFC 6455 "policy violation" code, which is what a
# browser surfaces for a rejected connection; the 4xxx codes are the
# application-defined range and let the app tell the two refusals apart.
WS_UNAUTHENTICATED = 4401
WS_NOT_YOUR_ORDER = 4403


async def _authorize(websocket: WebSocket, order_id: str, db: AsyncSession) -> bool:
    """Is the caller the customer who placed this order?

    The token arrives as a QUERY PARAMETER rather than an Authorization header
    because this app has a web target, and the browser WebSocket API cannot set
    request headers — there is no portable header channel on a WS handshake.
    The URL is wss:// in production, so the token is inside TLS; the real cost
    is that it can land in access logs, which is why it is a short-lived
    customer token and not a long-lived secret.

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

    # Staff tokens must not be usable here. This socket is scoped to one
    # customer's order, and `typ` is what separates the two token families
    # (see carevo_customer/deps.py).
    if payload.get("typ") != "customer":
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False

    customer_id = payload.get("sub")
    if not customer_id:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False

    try:
        row = (await db.execute(
            text("SELECT customer_id FROM customer_orders WHERE id = :oid"),
            {"oid": str(order_id)},
        )).first()
    except Exception:
        # order_id came off the wire; a non-UUID must be a refusal, not a 500.
        await db.rollback()
        await websocket.close(code=WS_NOT_YOUR_ORDER)
        return False

    # Unknown order and someone else's order are answered identically, so this
    # socket cannot be used to probe which order ids exist.
    if row is None or str(row[0]) != str(customer_id):
        await websocket.close(code=WS_NOT_YOUR_ORDER)
        return False

    return True


@router.websocket("/ws/order/{order_id}")
async def customer_order_websocket(
    websocket: WebSocket,
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Customer's phone connects here to track their order.
    URL: wss://<host>/ws/order/{order_id}?token=<customer JWT>

    AUTHENTICATED AND OWNERSHIP-SCOPED. This socket previously accepted any
    connection for any order id with no credential at all — order ids are
    UUIDs, but they are handed to the customer in a URL and shared, and the
    socket streams live order events plus accepts `request_bill` and
    `cancel_order` on the customer's behalf. Anyone holding or guessing an id
    could watch someone else's order and act on it.

    Events the customer receives:
    - ORDER_CONFIRMED:      Restaurant accepted the order
    - ORDER_STATUS_CHANGED: Status updated (in_kitchen, ready, served)
    - BILL_READY:           Bill has been generated

    Events the customer can send:
    - request_bill:         Customer wants the bill
    - cancel_order:         Customer wants to cancel (before confirmed)
    """
    # Authorise BEFORE accept, so a rejected handshake never becomes an open
    # socket and never reaches the connection manager.
    if not await _authorize(websocket, order_id, db):
        logger.info("Rejected customer WS for order %s", order_id)
        return

    await customer_manager.connect(websocket, order_id)
    logger.info(f"Customer connected for order {order_id}")

    try:
        # Send welcome message
        await websocket.send_text(json.dumps({
            "event": "CONNECTED",
            "order_id": order_id,
            "message": "Connected to order tracking",
        }))

        while True:
            data = await websocket.receive_text()
            logger.info(f"Customer message [{order_id}]: {data}")

            try:
                msg = json.loads(data)
                event = msg.get("event", "")

                if event == "request_bill":
                    # Customer is requesting the bill
                    # POS will handle this — for now just acknowledge
                    await websocket.send_text(json.dumps({
                        "event": "BILL_REQUESTED",
                        "order_id": order_id,
                        "message": "Bill request sent to staff",
                    }))

                elif event == "ping":
                    await websocket.send_text(json.dumps({
                        "event": "pong",
                        "order_id": order_id,
                    }))

                else:
                    await websocket.send_text(json.dumps({
                        "event": "ACK",
                        "received": data,
                    }))

            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "event": "ACK",
                    "received": data,
                }))

    except WebSocketDisconnect:
        customer_manager.disconnect(websocket, order_id)
        logger.info(f"Customer disconnected from order {order_id}")
