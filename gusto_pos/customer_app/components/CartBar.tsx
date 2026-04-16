'use client';

import { useCart } from '@/lib/cart-store';
import { useRouter } from 'next/navigation';

export default function CartBar() {
  const { totalItems, totalAmount } = useCart();
  const router = useRouter();

  if (totalItems === 0) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-slate-700 bg-[#1e293b] px-4 py-3 shadow-lg shadow-black/40">
      <div className="mx-auto flex max-w-md items-center justify-between">
        <div className="text-sm font-medium text-[#f8fafc]">
          <span className="font-bold text-[#f97316]">{totalItems}</span>{' '}
          {totalItems === 1 ? 'item' : 'items'} | <span className="font-bold">₹{totalAmount}</span>
        </div>
        <button
          onClick={() => router.push('/cart')}
          className="rounded-xl bg-[#f97316] px-6 py-2.5 text-sm font-bold text-white transition-colors hover:bg-[#ea580c] active:scale-95"
        >
          View Cart →
        </button>
      </div>
    </div>
  );
}
