import { API_BASE } from './api';

export const WS_BASE = (process.env.NEXT_PUBLIC_API_URL || API_BASE)
  .replace(/^http:/, 'ws:')
  .replace(/^https:/, 'wss:')
  .replace(/\/api\/v1\/?$/, '')
  .replace(/\/$/, '');

type EventHandler = (data: Record<string, unknown>) => void;

/**
 * Auto-reconnecting WebSocket with type-keyed event handlers.
 * Subscribe to a specific `type` field, or to '*' for every message.
 */
export class GustoWebSocket {
  private ws: WebSocket | null = null;
  private handlers: Map<string, EventHandler[]> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private url = '';
  private stopped = false;

  connect(url: string) {
    this.url = url;
    this.stopped = false;
    this.open();
  }

  private open() {
    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('WS connected:', this.url);
      };

      this.ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          const type = typeof data.type === 'string' ? data.type : '';
          [...(this.handlers.get(type) || []), ...(this.handlers.get('*') || [])].forEach((h) =>
            h(data)
          );
        } catch {
          // Ignore non-JSON frames
        }
      };

      this.ws.onclose = () => {
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    if (this.stopped || this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, 3000);
  }

  on(event: string, handler: EventHandler) {
    if (!this.handlers.has(event)) this.handlers.set(event, []);
    this.handlers.get(event)!.push(handler);
    return () => this.off(event, handler);
  }

  off(event: string, handler: EventHandler) {
    const handlers = this.handlers.get(event) || [];
    this.handlers.set(
      event,
      handlers.filter((h) => h !== handler)
    );
  }

  send(data: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  disconnect() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.ws?.close();
    this.ws = null;
  }
}

/** Live order-status channel for the customer sitting at `tableId`. */
export function createCustomerWS(tableId: string): GustoWebSocket {
  const ws = new GustoWebSocket();
  ws.connect(`${WS_BASE}/ws/customer/${encodeURIComponent(tableId)}`);
  return ws;
}

/**
 * Order-tracking socket keyed by order_id, speaking the legacy `{event: ...}`
 * vocabulary used by the /order/[id] page.
 */
export function connectOrderWebSocket(
  orderId: string,
  onMessage: (data: Record<string, unknown>) => void,
  onConnect?: () => void,
  onDisconnect?: () => void
): WebSocket {
  let ws: WebSocket;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  function connect() {
    ws = new WebSocket(`${WS_BASE}/ws/order/${orderId}`);

    ws.onopen = () => {
      console.log('Order WebSocket connected');
      onConnect?.();
    };

    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch (e) {
        console.error('WS parse error:', e);
      }
    };

    ws.onclose = (e) => {
      if (e.code !== 1000) {
        console.warn(`Order WebSocket closed (code ${e.code}). Retrying in 5s…`);
      }
      onDisconnect?.();
      if (!stopped) {
        reconnectTimer = setTimeout(connect, 5000);
      }
    };

    ws.onerror = () => {
      // onclose fires right after and handles reconnection
    };
  }

  connect();

  const proxy = Object.create(WebSocket.prototype);
  Object.defineProperty(proxy, 'readyState', { get: () => ws.readyState });
  proxy.send = (data: string) => ws.send(data);
  proxy.close = () => {
    stopped = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws.close();
  };

  return proxy as WebSocket;
}
