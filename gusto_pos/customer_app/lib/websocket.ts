const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';

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
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error('WS parse error:', e);
      }
    };

    ws.onclose = (e) => {
      // Code 1000 = normal closure, anything else is unexpected
      if (e.code !== 1000) {
        console.warn(`Order WebSocket closed (code ${e.code}). Retrying in 5s…`);
      }
      onDisconnect?.();
      // Auto-reconnect unless explicitly closed
      if (!stopped) {
        reconnectTimer = setTimeout(() => {
          connect();
        }, 5000);
      }
    };

    ws.onerror = () => {
      // Suppress noisy console errors — the onclose handler will
      // fire right after this and manage reconnection.
    };
  }

  connect();

  // Return a proxy-like object that forwards close() and readyState
  // but also stops reconnection when close() is called
  const proxy = Object.create(WebSocket.prototype);
  Object.defineProperty(proxy, 'readyState', {
    get: () => ws.readyState,
  });
  proxy.send = (data: string) => ws.send(data);
  proxy.close = () => {
    stopped = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws.close();
  };

  return proxy as WebSocket;
}
