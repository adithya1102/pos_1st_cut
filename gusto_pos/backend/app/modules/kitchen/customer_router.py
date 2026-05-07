from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.websocket_manager import customer_manager
import logging
import json

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Customer WebSocket"])


@router.websocket("/ws/order/{order_id}")
async def customer_order_websocket(websocket: WebSocket, order_id: str):
    """
    Customer's phone connects here to track their order.
    URL: ws://localhost:8000/ws/order/{order_id}

    Events the customer receives:
    - ORDER_CONFIRMED:      Restaurant accepted the order
    - ORDER_STATUS_CHANGED: Status updated (in_kitchen, ready, served)
    - BILL_READY:           Bill has been generated
    
    Events the customer can send:
    - request_bill:         Customer wants the bill
    - cancel_order:         Customer wants to cancel (before confirmed)
    """
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
