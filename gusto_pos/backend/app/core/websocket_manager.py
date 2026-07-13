from typing import Dict, List
from fastapi import WebSocket
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Single registry for every live socket in the system.

    Three channels:
      - waiter_connections:   outlet_id -> [WebSocket]   (GustoWaiter tablets)
      - pos_connections:      outlet_id -> [WebSocket]   (GustoPOS terminals)
      - customer_connections: table_id  -> WebSocket     (one phone per table)
    """

    def __init__(self):
        self.waiter_connections: Dict[str, List[WebSocket]] = {}
        self.pos_connections: Dict[str, List[WebSocket]] = {}
        self.customer_connections: Dict[str, WebSocket] = {}

    # ---- connect ---------------------------------------------------------
    async def connect_waiter(self, websocket: WebSocket, outlet_id: str):
        await websocket.accept()
        self.waiter_connections.setdefault(outlet_id, []).append(websocket)
        logger.info(f"Waiter connected to outlet {outlet_id} "
                    f"({len(self.waiter_connections[outlet_id])} live)")

    async def connect_pos(self, websocket: WebSocket, outlet_id: str):
        await websocket.accept()
        self.pos_connections.setdefault(outlet_id, []).append(websocket)
        logger.info(f"POS connected to outlet {outlet_id} "
                    f"({len(self.pos_connections[outlet_id])} live)")

    async def connect_customer(self, websocket: WebSocket, table_id: str):
        await websocket.accept()
        self.customer_connections[table_id] = websocket
        logger.info(f"Customer connected at table {table_id}")

    # ---- disconnect ------------------------------------------------------
    def disconnect_waiter(self, websocket: WebSocket, outlet_id: str):
        if outlet_id in self.waiter_connections:
            self.waiter_connections[outlet_id] = [
                ws for ws in self.waiter_connections[outlet_id] if ws != websocket
            ]

    def disconnect_pos(self, websocket: WebSocket, outlet_id: str):
        if outlet_id in self.pos_connections:
            self.pos_connections[outlet_id] = [
                ws for ws in self.pos_connections[outlet_id] if ws != websocket
            ]

    def disconnect_customer(self, table_id: str):
        self.customer_connections.pop(table_id, None)

    # ---- broadcast -------------------------------------------------------
    async def _broadcast(self, bucket: Dict[str, List[WebSocket]], key: str, event: dict):
        sockets = bucket.get(key)
        if not sockets:
            return
        dead = []
        for ws in sockets:
            try:
                await ws.send_json(event)
            except Exception as exc:
                logger.warning(f"Dropping dead socket on {key}: {exc}")
                dead.append(ws)
        for ws in dead:
            if ws in bucket.get(key, []):
                bucket[key].remove(ws)

    async def notify_waiters(self, outlet_id: str, event: dict):
        """Push event to ALL waiters for this outlet."""
        await self._broadcast(self.waiter_connections, outlet_id, event)

    async def notify_pos(self, outlet_id: str, event: dict):
        """Push event to ALL POS terminals for this outlet."""
        await self._broadcast(self.pos_connections, outlet_id, event)

    async def notify_customer(self, table_id: str, event: dict):
        """Push event to the customer sitting at a specific table."""
        ws = self.customer_connections.get(table_id)
        if not ws:
            return
        try:
            await ws.send_json(event)
        except Exception as exc:
            logger.warning(f"Dropping dead customer socket at table {table_id}: {exc}")
            self.customer_connections.pop(table_id, None)


manager = ConnectionManager()


class OutletChannel:
    """
    Legacy `{"event": NAME, ...}` broadcaster for the C# GustoPOS / GustoWaiter
    clients, backed by ConnectionManager's socket registry so both message
    formats reach the same sockets.
    """

    def __init__(self, bucket: str):
        self._bucket = bucket  # "pos" | "waiter"

    @property
    def active_connections(self) -> Dict[str, List[WebSocket]]:
        return getattr(manager, f"{self._bucket}_connections")

    async def connect(self, websocket: WebSocket, outlet_id: str):
        connect = getattr(manager, f"connect_{self._bucket}")
        await connect(websocket, outlet_id)

    def disconnect(self, websocket: WebSocket, outlet_id: str):
        getattr(manager, f"disconnect_{self._bucket}")(websocket, outlet_id)

    async def broadcast_to_outlet(self, outlet_id: str, message: dict):
        await manager._broadcast(self.active_connections, outlet_id, message)

    async def broadcast_order_event(self, outlet_id: str, event: str, order: dict):
        await self.broadcast_to_outlet(outlet_id, {"event": event, **order})

    async def broadcast_new_order(self, outlet_id: str, order: dict):
        await self.broadcast_to_outlet(outlet_id, {"event": "NEW_ORDER", **order})

    async def broadcast_status_update(self, outlet_id: str, order: dict):
        await self.broadcast_to_outlet(outlet_id, {
            "event": "ORDER_STATUS_UPDATED",
            "order_id": order.get("id"),
            "order_status": order.get("order_status"),
        })


# POS terminals and Waiter tablets — legacy event format, shared registry
pos_manager = OutletChannel("pos")
waiter_manager = OutletChannel("waiter")


class KitchenWebSocketManager:
    """
    Kitchen display sockets, keyed by outlet_id. Separate from ConnectionManager
    because kitchen screens speak their own event vocabulary.
    """

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, outlet_id: str):
        await websocket.accept()
        self.active_connections.setdefault(outlet_id, []).append(websocket)
        logger.info(f"Kitchen display connected to outlet {outlet_id}. "
                    f"Total screens: {len(self.active_connections[outlet_id])}")

    def disconnect(self, websocket: WebSocket, outlet_id: str):
        if outlet_id in self.active_connections:
            if websocket in self.active_connections[outlet_id]:
                self.active_connections[outlet_id].remove(websocket)
            if not self.active_connections[outlet_id]:
                del self.active_connections[outlet_id]

    async def broadcast_to_outlet(self, outlet_id: str, message: dict):
        if outlet_id not in self.active_connections:
            return
        disconnected = []
        payload = json.dumps(message)
        for websocket in self.active_connections[outlet_id]:
            try:
                await websocket.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to kitchen screen: {e}")
                disconnected.append(websocket)
        for ws in disconnected:
            if ws in self.active_connections.get(outlet_id, []):
                self.active_connections[outlet_id].remove(ws)

    async def broadcast_new_order(self, outlet_id: str, order: dict):
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
        await self.broadcast_to_outlet(outlet_id, {
            "event": "ORDER_STATUS_UPDATED",
            "order_id": order.get("id"),
            "kitchen_token": order.get("kitchen_token"),
            "order_status": order.get("order_status"),
        })

    async def broadcast_order_event(self, outlet_id: str, event: str, order: dict):
        await self.broadcast_to_outlet(outlet_id, {"event": event, **order})


kitchen_manager = KitchenWebSocketManager()


class CustomerWebSocketManager:
    """
    Customer phone sockets keyed by order_id (order-tracking page).
    Table-keyed customer sockets live on ConnectionManager instead.
    """

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, order_id: str):
        await websocket.accept()
        self.active_connections.setdefault(order_id, []).append(websocket)
        logger.info(f"Customer connected for order {order_id}")

    def disconnect(self, websocket: WebSocket, order_id: str):
        if order_id in self.active_connections:
            if websocket in self.active_connections[order_id]:
                self.active_connections[order_id].remove(websocket)
            if not self.active_connections[order_id]:
                del self.active_connections[order_id]

    async def send_order_update(self, order_id: str, message: dict):
        if order_id not in self.active_connections:
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
        await self.send_order_update(order_id, {
            "event": "ORDER_CONFIRMED",
            "order_id": order_id,
            "order_status": order.get("order_status"),
            "message": "Your order has been confirmed!",
            "kitchen_token": order.get("kitchen_token"),
        })

    async def notify_status_changed(self, order_id: str, order: dict):
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
        await self.send_order_update(order_id, {
            "event": "BILL_READY",
            "order_id": order_id,
            "amount": amount,
            "message": f"Your bill is ready: ₹{amount}",
        })


customer_manager = CustomerWebSocketManager()
