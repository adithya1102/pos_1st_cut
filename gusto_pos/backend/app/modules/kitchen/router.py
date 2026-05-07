from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.websocket_manager import kitchen_manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Kitchen Display"])

@router.websocket("/ws/kitchen/{outlet_id}")
async def kitchen_websocket(websocket: WebSocket, outlet_id: str):
    """
    Kitchen display connects here.
    URL: ws://localhost:8000/ws/kitchen/{outlet_id}
    
    The kitchen screen for outlet X connects to:
    ws://localhost:8000/ws/kitchen/0b8a8349-6144-41a8-b028-b9089bd8eaea
    
    It then receives real-time events:
    - NEW_ORDER: when a waiter submits a new order
    - ORDER_STATUS_UPDATED: when status changes
    """
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
