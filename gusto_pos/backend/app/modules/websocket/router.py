import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.websocket_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])


@router.websocket("/waiter/{outlet_id}")
async def waiter_ws(websocket: WebSocket, outlet_id: str):
    """GustoWaiter connects here to receive real-time order alerts."""
    await manager.connect_waiter(websocket, outlet_id)
    try:
        while True:
            await websocket.receive_text()
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect_waiter(websocket, outlet_id)
        logger.info(f"Waiter disconnected from outlet {outlet_id}")


@router.websocket("/pos/{outlet_id}")
async def pos_ws(websocket: WebSocket, outlet_id: str):
    """GustoPOS connects here to receive table status updates."""
    await manager.connect_pos(websocket, outlet_id)
    try:
        while True:
            await websocket.receive_text()
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect_pos(websocket, outlet_id)
        logger.info(f"POS disconnected from outlet {outlet_id}")


@router.websocket("/customer/{table_id}")
async def customer_ws(websocket: WebSocket, table_id: str):
    """Customer browser connects here to get order status updates for its table."""
    await manager.connect_customer(websocket, table_id)
    try:
        while True:
            await websocket.receive_text()
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect_customer(table_id)
        logger.info(f"Customer disconnected from table {table_id}")
