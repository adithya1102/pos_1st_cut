'use client';

import { OrderStatus as OrderStatusType } from '@/lib/types';

const STATUS_CONFIG: Record<
  OrderStatusType,
  { icon: string; color: string; bgColor: string; label: string }
> = {
  pending: {
    icon: '🕐',
    color: '#eab308',
    bgColor: 'rgba(234,179,8,0.15)',
    label: 'Order received',
  },
  confirmed: {
    icon: '✅',
    color: '#3b82f6',
    bgColor: 'rgba(59,130,246,0.15)',
    label: 'Order confirmed',
  },
  in_kitchen: {
    icon: '👨‍🍳',
    color: '#f97316',
    bgColor: 'rgba(249,115,22,0.15)',
    label: 'Being prepared',
  },
  ready: {
    icon: '🍽️',
    color: '#22c55e',
    bgColor: 'rgba(34,197,94,0.15)',
    label: 'Ready to serve!',
  },
  served: {
    icon: '😊',
    color: '#a855f7',
    bgColor: 'rgba(168,85,247,0.15)',
    label: 'Enjoy your meal!',
  },
  completed: {
    icon: '🏁',
    color: '#64748b',
    bgColor: 'rgba(100,116,139,0.15)',
    label: 'Thank you!',
  },
  cancelled: {
    icon: '❌',
    color: '#ef4444',
    bgColor: 'rgba(239,68,68,0.15)',
    label: 'Order cancelled',
  },
};

interface OrderStatusProps {
  status: OrderStatusType;
}

export default function OrderStatus({ status }: OrderStatusProps) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending;

  return (
    <div
      className="flex flex-col items-center gap-3 rounded-2xl p-8"
      style={{ backgroundColor: config.bgColor }}
    >
      <span className="text-6xl">{config.icon}</span>
      <h2 className="text-2xl font-bold" style={{ color: config.color }}>
        {config.label}
      </h2>
      <p className="text-sm text-slate-400 capitalize">{status.replace('_', ' ')}</p>
    </div>
  );
}
