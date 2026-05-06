from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.websocket_manager import pos_manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["POS Terminal"])


@router.websocket("/ws/pos/{outlet_id}")
async def pos_websocket(websocket: WebSocket, outlet_id: str):
    """
    POS terminal connects here to receive live order events.
    URL: ws://localhost:8000/ws/pos/{outlet_id}

    Events pushed to the POS:
    - NEW_ORDER: new order placed for an outlet table
    - ORDER_CONFIRMED: waiter confirmed an order
    - ORDER_STATUS_UPDATED: order status changed
    """
    await pos_manager.connect(websocket, outlet_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pos_manager.disconnect(websocket, outlet_id)
        logger.info(f"POS terminal disconnected from outlet {outlet_id}")
