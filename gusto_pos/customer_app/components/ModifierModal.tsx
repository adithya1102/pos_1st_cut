'use client';

import { useState } from 'react';
import { MenuItem, MenuModifier } from '@/lib/types';

interface ModifierModalProps {
  item: MenuItem;
  onConfirm: (item: MenuItem, selectedModifiers: MenuModifier[]) => void;
  onClose: () => void;
}

export default function ModifierModal({ item, onConfirm, onClose }: ModifierModalProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const toggle = (modifierId: string) => {
    setSelected((prev) => ({ ...prev, [modifierId]: !prev[modifierId] }));
  };

  const selectedModifiers = (item.modifiers || []).filter((m) => selected[m.id]);
  const modTotal = selectedModifiers.reduce((sum, m) => sum + m.extra_price, 0);
  const total = (item.price ?? item.base_price ?? 0) + modTotal;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center">
      <div className="w-full max-w-md rounded-t-2xl bg-[#1e293b] p-6 sm:rounded-2xl">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
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
              <h2 className="text-lg font-bold text-[#f8fafc]">{item.name}</h2>
            </div>
            <p className="mt-1 text-sm text-[#f97316]">₹{item.price ?? item.base_price ?? 0}</p>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 hover:bg-slate-700 hover:text-white"
          >
            ✕
          </button>
        </div>

        {/* Modifiers */}
        <div className="mb-6">
          <h3 className="mb-3 text-sm font-semibold text-slate-300 uppercase tracking-wide">
            Add-ons
          </h3>
          <div className="space-y-2">
            {(item.modifiers || []).map((mod) => (
              <label
                key={mod.id}
                className="flex cursor-pointer items-center justify-between rounded-lg bg-[#0f172a] p-3"
              >
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={!!selected[mod.id]}
                    onChange={() => toggle(mod.id)}
                    className="h-5 w-5 rounded border-slate-600 bg-transparent text-[#f97316] accent-[#f97316]"
                  />
                  <span className="text-sm text-[#f8fafc]">{mod.modifier_name}</span>
                </div>
                <span className="text-sm text-slate-400">+₹{mod.extra_price}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Footer */}
        <button
          onClick={() => onConfirm(item, selectedModifiers)}
          className="w-full rounded-xl bg-[#f97316] py-3 text-center text-base font-bold text-white transition-colors hover:bg-[#ea580c] active:scale-[0.98]"
        >
          Add to cart — ₹{total}
        </button>
      </div>
    </div>
  );
}
