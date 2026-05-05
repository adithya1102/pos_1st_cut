from typing import Dict, List
from fastapi import WebSocket
import json
import logging

logger = logging.getLogger(__name__)

class KitchenWebSocketManager:
    """
    Manages WebSocket connections for kitchen displays.
    Each outlet has its own channel (keyed by outlet_id).
    Multiple kitchen screens can connect to the same outlet channel.
    """

    def __init__(self):
        # outlet_id -> list of connected websockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, outlet_id: str):
        await websocket.accept()
        if outlet_id not in self.active_connections:
            self.active_connections[outlet_id] = []
        self.active_connections[outlet_id].append(websocket)
        logger.info(f"Kitchen display connected to outlet {outlet_id}. "
                    f"Total screens: {len(self.active_connections[outlet_id])}")

    def disconnect(self, websocket: WebSocket, outlet_id: str):
        if outlet_id in self.active_connections:
            self.active_connections[outlet_id].remove(websocket)
            if not self.active_connections[outlet_id]:
                del self.active_connections[outlet_id]
        logger.info(f"Kitchen display disconnected from outlet {outlet_id}")

    async def broadcast_to_outlet(self, outlet_id: str, message: dict):
        """Send a message to all kitchen screens connected to this outlet."""
        if outlet_id not in self.active_connections:
            logger.info(f"No kitchen screens connected to outlet {outlet_id}")
            return

        disconnected = []
        payload = json.dumps(message)

        for websocket in self.active_connections[outlet_id]:
            try:
                await websocket.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to screen: {e}")
                disconnected.append(websocket)

        # Clean up dead connections
        for ws in disconnected:
            self.active_connections[outlet_id].remove(ws)

    async def broadcast_new_order(self, outlet_id: str, order: dict):
        """Notify kitchen of a new order."""
        await self.broadcast_to_outlet(outlet_id, {
            "event": "NEW_ORDER",
            "order_id": order.get("id"),
            "kitchen_token": order.get("kitchen_token"),
            "table_id": order.get("table_id"),
            "customer_id": order.get("customer_id"),
            "total_amount": order.get("total_amount"),
            "order_status": order.get("order_status"),
            "created_at": str(order.get("created_at")),
        })

    async def broadcast_status_update(self, outlet_id: str, order: dict):
        """Notify kitchen of an order status change."""
        await self.broadcast_to_outlet(outlet_id, {
            "event": "ORDER_STATUS_UPDATED",
            "order_id": order.get("id"),
            "kitchen_token": order.get("kitchen_token"),
            "order_status": order.get("order_status"),
        })

# Singleton instance — shared across all requests
kitchen_manager = KitchenWebSocketManager()


class CustomerWebSocketManager:
    """
    Manages WebSocket connections for customer phones.
    Each order has its own channel (keyed by order_id).
    The customer connects to track THEIR order status only.
    """

    def __init__(self):
        # order_id -> list of connected websockets (usually just 1)
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, order_id: str):
        await websocket.accept()
        if order_id not in self.active_connections:
            self.active_connections[order_id] = []
        self.active_connections[order_id].append(websocket)
        logger.info(f"Customer connected for order {order_id}")

    def disconnect(self, websocket: WebSocket, order_id: str):
        if order_id in self.active_connections:
            if websocket in self.active_connections[order_id]:
                self.active_connections[order_id].remove(websocket)
            if not self.active_connections[order_id]:
                del self.active_connections[order_id]
        logger.info(f"Customer disconnected from order {order_id}")

    async def send_order_update(self, order_id: str, message: dict):
        """Send order status update to the customer's phone."""
        if order_id not in self.active_connections:
            logger.info(f"No customer connected for order {order_id}")
            return

        disconnected = []
        payload = json.dumps(message)

        for websocket in self.active_connections[order_id]:
            try:
                await websocket.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to customer: {e}")
                disconnected.append(websocket)

        for ws in disconnected:
            if ws in self.active_connections.get(order_id, []):
                self.active_connections[order_id].remove(ws)

    async def notify_order_confirmed(self, order_id: str, order: dict):
        """Tell customer their order was confirmed by restaurant."""
        await self.send_order_update(order_id, {
            "event": "ORDER_CONFIRMED",
            "order_id": order_id,
            "order_status": order.get("order_status"),
            "message": "Your order has been confirmed!",
            "kitchen_token": order.get("kitchen_token"),
        })

    async def notify_status_changed(self, order_id: str, order: dict):
        """Tell customer their order status changed."""
        status = order.get("order_status", "")
        messages = {
            "confirmed":   "Your order is confirmed!",
            "in_kitchen":  "Your food is being prepared 👨‍🍳",
            "ready":       "Your food is ready! 🍽️",
            "served":      "Enjoy your meal! 😊",
            "completed":   "Thank you for dining with us!",
            "cancelled":   "Your order was cancelled.",
        }
        await self.send_order_update(order_id, {
            "event": "ORDER_STATUS_CHANGED",
            "order_id": order_id,
            "order_status": status,
            "message": messages.get(status, f"Order status: {status}"),
        })

    async def notify_bill_ready(self, order_id: str, amount: float):
        """Tell customer their bill is ready."""
        await self.send_order_update(order_id, {
            "event": "BILL_READY",
            "order_id": order_id,
            "amount": amount,
            "message": f"Your bill is ready: ₹{amount}",
        })


# Singleton instance for customer connections
customer_manager = CustomerWebSocketManager()

# Singleton instance for POS terminal connections (outlet-keyed, same pattern as kitchen_manager)
pos_manager = KitchenWebSocketManager()
