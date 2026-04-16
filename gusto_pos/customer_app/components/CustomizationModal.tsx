'use client';

import { useState } from 'react';
import { MenuItem } from '@/lib/types';

interface CustomizationModalProps {
  item: MenuItem;
  onConfirm: (
    item: MenuItem,
    customizations: string[],
    customNote: string,
    quantity: number
  ) => void;
  onClose: () => void;
}

function parseAddonPrice(option: string): number {
  const match = option.match(/\+₹(\d+)/);
  return match ? parseInt(match[1], 10) : 0;
}

export default function CustomizationModal({
  item,
  onConfirm,
  onClose,
}: CustomizationModalProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [quantity, setQuantity] = useState(1);
  const [customNote, setCustomNote] = useState('');

  const toggle = (option: string) => {
    setSelected((prev) => ({ ...prev, [option]: !prev[option] }));
  };

  const selectedOptions = (item.customization_options || []).filter((o) => selected[o]);
  const addonTotal = selectedOptions.reduce((sum, o) => sum + parseAddonPrice(o), 0);
  const itemPrice = item.price ?? item.base_price ?? 0;
  const total = (itemPrice + addonTotal) * quantity;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center"
      onClick={onClose}
    >
      {/* Overlay */}
      <div className="absolute inset-0 bg-black/50" />

      {/* Modal */}
      <div
        className="relative w-full max-w-md rounded-t-[20px] bg-white p-6 shadow-xl"
        style={{ maxHeight: '85vh', overflowY: 'auto' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-5 flex items-start justify-between">
          <div>
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
              <h2 className="text-lg font-bold text-[#212529]">{item.name}</h2>
            </div>
            <p className="mt-1 text-base font-semibold text-[#212529]">₹{itemPrice}</p>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            ✕
          </button>
        </div>

        {/* Section 1: Quick Options */}
        {item.customization_options && item.customization_options.length > 0 && (
          <div className="mb-5">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
              Quick Options
            </h3>
            <div className="space-y-2">
              {item.customization_options.map((option) => {
                const addonPrice = parseAddonPrice(option);
                return (
                  <label
                    key={option}
                    className="flex cursor-pointer items-center justify-between rounded-lg border border-gray-200 p-3 transition-colors hover:bg-gray-50"
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={!!selected[option]}
                        onChange={() => toggle(option)}
                        className="h-5 w-5 rounded border-gray-300"
                        style={{ accentColor: '#1B4332' }}
                      />
                      <span className="text-sm text-[#212529]">{option}</span>
                    </div>
                    {addonPrice > 0 && (
                      <span className="text-sm font-medium text-gray-500">+₹{addonPrice}</span>
                    )}
                  </label>
                );
              })}
            </div>
          </div>
        )}

        {/* Section 2: Quantity */}
        <div className="mb-5">
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            Quantity
          </h3>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setQuantity((q) => Math.max(1, q - 1))}
              className="flex h-10 w-10 items-center justify-center rounded-lg border border-gray-300 text-lg font-bold text-[#212529] hover:bg-gray-100"
            >
              −
            </button>
            <span className="min-w-[32px] text-center text-lg font-bold text-[#212529]">
              {quantity}
            </span>
            <button
              onClick={() => setQuantity((q) => q + 1)}
              className="flex h-10 w-10 items-center justify-center rounded-lg border border-gray-300 text-lg font-bold text-[#212529] hover:bg-gray-100"
            >
              +
            </button>
          </div>
        </div>

        {/* Section 3: Custom Note */}
        <div className="mb-6">
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            Special Request
          </h3>
          <input
            type="text"
            value={customNote}
            onChange={(e) => setCustomNote(e.target.value.slice(0, 200))}
            placeholder="Any special request? (e.g. no red chilli)"
            maxLength={200}
            className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm text-[#212529] placeholder-gray-400 outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
          />
          <p className="mt-1 text-right text-xs text-gray-400">{customNote.length}/200</p>
        </div>

        {/* Add to Order Button */}
        <button
          onClick={() => onConfirm(item, selectedOptions, customNote, quantity)}
          className="w-full rounded-xl py-4 text-center text-base font-bold text-white transition-colors hover:opacity-90 active:scale-[0.98]"
          style={{ backgroundColor: '#28A745' }}
        >
          Add to Order — ₹{total}
        </button>
      </div>
    </div>
  );
}
