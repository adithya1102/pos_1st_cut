'use client';

import { useCart } from '@/lib/cart-store';
import { createOrder } from '@/lib/api';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState, useEffect, Suspense } from 'react';

interface OrderResult {
  id: string;
  readable_id?: number;
  kitchen_token?: string;
}

export default function CartPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center bg-[#0f172a]">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#f97316] border-t-transparent" />
      </div>
    }>
      <CartContent />
    </Suspense>
  );
}

function CartContent() {
  const {
    items,
    totalAmount,
    totalItems,
    increaseQuantity,
    decreaseQuantity,
    clearCart,
    outletId,
    tableId,
  } = useCart();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [placing, setPlacing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [orderSuccess, setOrderSuccess] = useState<OrderResult | null>(null);
  const [zone, setZone] = useState('normal');

  useEffect(() => {
    const z = searchParams.get('zone') || localStorage.getItem('table_zone') || 'normal';
    setZone(z);
  }, [searchParams]);

  const handlePlaceOrder = async () => {
    if (items.length === 0) return;
    setPlacing(true);
    setError(null);
    try {
      const orderData = {
        outlet_id: outletId,
        table_id: tableId,
        total_amount: totalAmount,
        order_type: 'dine_in',
        zone,
        source: 'customer',
        items: items.map((item) => ({
          name: item.name,
          quantity: item.quantity,
          unit_price: item.price,
          customizations: item.customizations,
          custom_note: item.custom_note,
        })),
      };
      const order = await createOrder(orderData);
      clearCart();
      setOrderSuccess(order);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to place order');
    } finally {
      setPlacing(false);
    }
  };

  // Success screen
  if (orderSuccess) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-[#0f172a] px-4">
        <div className="text-center">
          <div className="mb-4 text-7xl animate-bounce">✅</div>
          <h2 className="text-2xl font-bold text-[#f8fafc]">Order Sent! 🎉</h2>
          <p className="mt-3 text-base text-slate-300">
            Order #{orderSuccess.readable_id || orderSuccess.id.slice(0, 8)}
          </p>
          <p className="mt-2 text-sm text-slate-400">Your waiter has been notified</p>
          <p className="mt-1 text-sm text-slate-500">Estimated time: 20-30 minutes</p>
        </div>
        <button
          onClick={() => router.push('/menu')}
          className="mt-8 rounded-xl bg-[#f97316] px-8 py-3 text-base font-bold text-white hover:bg-[#ea580c]"
        >
          Back to Menu
        </button>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-[#0f172a] px-4">
        <span className="text-6xl">🛒</span>
        <h2 className="mt-4 text-xl font-bold text-[#f8fafc]">Your cart is empty</h2>
        <p className="mt-2 text-sm text-slate-400">Add some delicious items from the menu</p>
        <button
          onClick={() => router.push('/menu')}
          className="mt-6 rounded-xl bg-[#f97316] px-6 py-3 text-sm font-bold text-white hover:bg-[#ea580c]"
        >
          Browse Menu
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0f172a] pb-40">
      {/* Header */}
      <div className="sticky top-0 z-30 bg-[#0f172a]/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-md items-center gap-3 px-4 py-4">
          <button
            onClick={() => router.push('/menu')}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-[#1e293b] text-slate-400 hover:text-white"
          >
            ←
          </button>
          <div>
            <h1 className="text-lg font-bold text-[#f8fafc]">Your Cart</h1>
            <p className="text-xs text-slate-500">
              {totalItems} {totalItems === 1 ? 'item' : 'items'}
            </p>
          </div>
        </div>
      </div>

      {/* Cart items */}
      <div className="mx-auto max-w-md space-y-3 px-4">
        {items.map((item, index) => (
          <div
            key={`${item.id}-${index}`}
            className="rounded-xl bg-[#1e293b] p-4"
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex h-4 w-4 items-center justify-center rounded-sm border ${
                      item.is_veg ? 'border-[#22c55e]' : 'border-[#ef4444]'
                    }`}
                  >
                    <span
                      className={`h-2 w-2 rounded-full ${
                        item.is_veg ? 'bg-[#22c55e]' : 'bg-[#ef4444]'
                      }`}
                    />
                  </span>
                  <h3 className="text-base font-semibold text-[#f8fafc]">{item.name}</h3>
                </div>
                {item.customizations.length > 0 && (
                  <p className="mt-1 text-xs italic text-slate-400">
                    {item.customizations.join(', ')}
                  </p>
                )}
                {item.custom_note && (
                  <p className="mt-0.5 text-xs italic text-slate-500">
                    Note: {item.custom_note}
                  </p>
                )}
                <p className="mt-2 text-sm font-medium text-[#f97316]">₹{item.item_total}</p>
              </div>

              {/* Quantity controls */}
              <div className="flex items-center gap-3 rounded-lg bg-[#0f172a] px-2 py-1">
                <button
                  onClick={() => decreaseQuantity(index)}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-lg font-bold text-[#f97316] hover:bg-slate-700"
                >
                  −
                </button>
                <span className="min-w-[20px] text-center text-sm font-bold text-[#f8fafc]">
                  {item.quantity}
                </span>
                <button
                  onClick={() => increaseQuantity(index)}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-lg font-bold text-[#f97316] hover:bg-slate-700"
                >
                  +
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Order summary footer */}
      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-slate-700 bg-[#1e293b] px-4 py-4 shadow-lg shadow-black/40">
        <div className="mx-auto max-w-md">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm text-slate-400">Subtotal</span>
            <span className="text-lg font-bold text-[#f8fafc]">₹{totalAmount}</span>
          </div>

          {error && (
            <p className="mb-3 text-center text-sm text-[#ef4444]">{error}</p>
          )}

          <button
            onClick={handlePlaceOrder}
            disabled={placing}
            className="w-full rounded-xl py-3.5 text-center text-lg font-bold text-white transition-colors hover:opacity-90 disabled:opacity-50 active:scale-[0.98]"
            style={{ backgroundColor: '#1B4332', height: '56px', fontSize: '18px' }}
          >
            {placing ? (
              <span className="flex items-center justify-center gap-2">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Sending order...
              </span>
            ) : (
              'Confirm Order 🛎️'
            )}
          </button>
          <p className="mt-2 text-center text-xs text-slate-500">
            Your waiter will review and send to kitchen
          </p>
        </div>
      </div>
    </div>
  );
}
