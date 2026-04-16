'use client';

import { MenuItem } from '@/lib/types';

interface MenuItemCardProps {
  item: MenuItem;
  onAdd: (item: MenuItem) => void;
}

export default function MenuItemCard({ item, onAdd }: MenuItemCardProps) {
  const displayPrice = item.price ?? item.base_price ?? 0;

  return (
    <div className="flex items-center justify-between rounded-xl bg-[#1e293b] p-4">
      <div className="flex-1 pr-3">
        <div className="mb-1 flex items-center gap-2">
          {/* Veg / Non-veg badge */}
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
          <span className="text-xs font-medium text-slate-400 uppercase">
            {item.is_veg ? 'Veg' : 'Non-Veg'}
          </span>
        </div>
        <h3 className="text-base font-semibold text-[#f8fafc]">{item.name}</h3>
        <p className="mt-1 text-sm font-medium text-[#f97316]">₹{displayPrice}</p>
        {item.customization_options && item.customization_options.length > 0 && (
          <p className="mt-1 text-xs text-slate-500">Customisable</p>
        )}
      </div>
      <button
        onClick={() => onAdd(item)}
        className="flex h-9 w-20 items-center justify-center rounded-lg border border-[#f97316] bg-transparent text-sm font-bold text-[#f97316] transition-colors hover:bg-[#f97316] hover:text-white active:scale-95"
      >
        ADD
      </button>
    </div>
  );
}
