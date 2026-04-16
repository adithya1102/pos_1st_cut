'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { connectOrderWebSocket } from '@/lib/websocket';
import { fetchOrder } from '@/lib/api';
import { Order, OrderStatus as OrderStatusType } from '@/lib/types';
import OrderStatusDisplay from '@/components/OrderStatus';
import ProgressBar from '@/components/ProgressBar';

export default function OrderTrackingPage() {
  const params = useParams();
  const orderId = params.id as string;

  const [order, setOrder] = useState<Order | null>(null);
  const [status, setStatus] = useState<OrderStatusType>('pending');
  const [connected, setConnected] = useState(false);
  const [billRequested, setBillRequested] = useState(false);
  const [loading, setLoading] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);

  // Fetch initial order data
  useEffect(() => {
    if (!orderId) return;
    fetchOrder(orderId)
      .then((data) => {
        setOrder(data);
        setStatus(data.order_status as OrderStatusType);
      })
      .catch((err) => console.error('Failed to fetch order:', err))
      .finally(() => setLoading(false));
  }, [orderId]);

  // Connect WebSocket
  useEffect(() => {
    if (!orderId) return;

    const ws = connectOrderWebSocket(
      orderId,
      (data) => {
        console.log('WS message:', data);
        // Handle status update events
        if (data.event === 'ORDER_STATUS_CHANGED' || data.order_status) {
          const newStatus = (data.new_status || data.order_status) as OrderStatusType;
          if (newStatus) setStatus(newStatus);
        }
        if (data.event === 'bill_requested_ack') {
          setBillRequested(true);
        }
      },
      () => setConnected(true),
      () => setConnected(false)
    );

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [orderId]);

  const requestBill = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ event: 'request_bill' }));
      setBillRequested(true);
    }
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0f172a]">
        <div className="flex flex-col items-center gap-4">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#f97316] border-t-transparent" />
          <p className="text-sm text-slate-400">Loading order...</p>
        </div>
      </div>
    );
  }

  const showBillButton = (status === 'ready' || status === 'served') && !billRequested;
  const token = order?.kitchen_token || order?.readable_id || orderId.slice(0, 8);

  return (
    <div className="min-h-screen bg-[#0f172a] px-4 py-6">
      <div className="mx-auto max-w-md">
        {/* Header */}
        <div className="mb-8 text-center">
          <h1 className="text-xl font-bold text-[#f8fafc]">
            🍽️ <span className="text-[#f97316]">Gusto</span>
          </h1>
          <p className="mt-1 text-sm text-slate-400">Order Tracking</p>
        </div>

        {/* Token number */}
        <div className="mb-6 rounded-2xl bg-[#1e293b] p-6 text-center">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">
            Kitchen Token
          </p>
          <p className="mt-2 text-5xl font-black text-[#f97316]">#{token}</p>
          {order?.total_amount && (
            <p className="mt-3 text-sm text-slate-400">
              Total: <span className="font-semibold text-[#f8fafc]">₹{order.total_amount}</span>
            </p>
          )}
        </div>

        {/* Status display */}
        <div className="mb-6">
          <OrderStatusDisplay status={status} />
        </div>

        {/* Progress bar */}
        <div className="mb-6 rounded-2xl bg-[#1e293b] p-6">
          <ProgressBar status={status} />
        </div>

        {/* WebSocket connection indicator */}
        <div className="mb-6 flex items-center justify-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${connected ? 'bg-[#22c55e]' : 'bg-[#ef4444]'}`}
          />
          <span className="text-xs text-slate-500">
            {connected ? 'Live updates active' : 'Reconnecting...'}
          </span>
        </div>

        {/* Request Bill button */}
        {showBillButton && (
          <button
            onClick={requestBill}
            className="w-full rounded-xl bg-[#a855f7] py-3.5 text-center text-base font-bold text-white transition-colors hover:bg-[#9333ea] active:scale-[0.98]"
          >
            🧾 Request Bill
          </button>
        )}

        {/* Bill requested confirmation */}
        {billRequested && (
          <div className="rounded-xl bg-[#a855f7]/15 p-4 text-center">
            <p className="text-sm font-medium text-[#a855f7]">
              🧾 Bill requested — staff will assist you
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
