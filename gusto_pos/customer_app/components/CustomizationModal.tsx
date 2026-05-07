'use client';

import { useState } from 'react';
import { MenuItem, ModifierOption } from '@/lib/types';

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

// Normalise the raw customization_options array from the API.
// The backend now returns ModifierOption[] (objects with id, label, etc.).
// Guard against legacy string[] format just in case.
function normalizeOptions(raw: ModifierOption[] | string[]): ModifierOption[] {
  if (!Array.isArray(raw) || raw.length === 0) return [];
  if (typeof raw[0] === 'string') {
    // Legacy: convert plain strings to synthetic ModifierOption objects
    return (raw as string[]).map((s, i) => {
      const priceMatch = s.match(/\+₹(\d+)/);
      return {
        id: `legacy-${i}`,
        label: s,
        extra_price: priceMatch ? parseInt(priceMatch[1], 10) : 0,
        modifier_type: 'checkbox' as const,
        group_name: null,
      };
    });
  }
  return raw as ModifierOption[];
}

export default function CustomizationModal({
  item,
  onConfirm,
  onClose,
}: CustomizationModalProps) {
  // checkedOptions tracks selected checkbox modifier ids
  const [checkedOptions, setCheckedOptions] = useState<Set<string>>(new Set());
  // radioSelections maps group_name → selected modifier id
  const [radioSelections, setRadioSelections] = useState<Record<string, string>>({});
  const [quantity, setQuantity] = useState(1);
  const [customNote, setCustomNote] = useState('');

  const allOptions = normalizeOptions(item.customization_options);

  // Separate into radio groups and standalone checkboxes
  const radioGroups: Record<string, ModifierOption[]> = {};
  const checkboxOptions: ModifierOption[] = [];
  for (const opt of allOptions) {
    if (opt.modifier_type === 'radio' && opt.group_name) {
      if (!radioGroups[opt.group_name]) radioGroups[opt.group_name] = [];
      radioGroups[opt.group_name].push(opt);
    } else {
      checkboxOptions.push(opt);
    }
  }

  const toggleCheckbox = (id: string) => {
    setCheckedOptions((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectRadio = (groupName: string, id: string) => {
    setRadioSelections((prev) => ({ ...prev, [groupName]: id }));
  };

  // Calculate total upcharge from selected paid modifiers
  const addonTotal =
    allOptions
      .filter((opt) => {
        if (opt.modifier_type === 'radio' && opt.group_name) {
          return radioSelections[opt.group_name] === opt.id;
        }
        return checkedOptions.has(opt.id);
      })
      .reduce((sum, opt) => sum + opt.extra_price, 0);

  const itemPrice = item.price ?? item.base_price ?? 0;
  const total = (itemPrice + addonTotal) * quantity;

  const handleConfirm = () => {
    // Build flat string[] output for the cart store
    const selections: string[] = [];

    // Checkbox selections
    for (const opt of checkboxOptions) {
      if (checkedOptions.has(opt.id)) {
        const label = opt.extra_price > 0 ? `${opt.label} +₹${opt.extra_price}` : opt.label;
        selections.push(label);
      }
    }

    // Radio selections
    for (const [groupName, selectedId] of Object.entries(radioSelections)) {
      const opts = radioGroups[groupName] || [];
      const chosen = opts.find((o) => o.id === selectedId);
      if (chosen) {
        selections.push(`${groupName}: ${chosen.label}`);
      }
    }

    onConfirm(item, selections, customNote, quantity);
  };

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

        {/* Radio groups */}
        {Object.entries(radioGroups).map(([groupName, opts]) => (
          <div key={groupName} className="mb-5">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
              {groupName.replace(/_/g, ' ')}
            </h3>
            <div className="space-y-2">
              {opts.map((opt) => (
                <label
                  key={opt.id}
                  className={`flex cursor-pointer items-center justify-between rounded-lg border p-3 transition-colors hover:bg-gray-50 ${
                    radioSelections[groupName] === opt.id
                      ? 'border-[#1B4332] bg-green-50'
                      : 'border-gray-200'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="radio"
                      name={groupName}
                      checked={radioSelections[groupName] === opt.id}
                      onChange={() => selectRadio(groupName, opt.id)}
                      className="h-5 w-5 border-gray-300"
                      style={{ accentColor: '#1B4332' }}
                    />
                    <span className="text-sm text-[#212529]">{opt.label}</span>
                  </div>
                  {opt.extra_price > 0 && (
                    <span className="text-sm font-medium text-gray-500">+₹{opt.extra_price}</span>
                  )}
                </label>
              ))}
            </div>
          </div>
        ))}

        {/* Checkbox options */}
        {checkboxOptions.length > 0 && (
          <div className="mb-5">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
              Quick Options
            </h3>
            <div className="space-y-2">
              {checkboxOptions.map((opt) => (
                <label
                  key={opt.id}
                  className={`flex cursor-pointer items-center justify-between rounded-lg border p-3 transition-colors hover:bg-gray-50 ${
                    checkedOptions.has(opt.id)
                      ? 'border-[#1B4332] bg-green-50'
                      : 'border-gray-200'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={checkedOptions.has(opt.id)}
                      onChange={() => toggleCheckbox(opt.id)}
                      className="h-5 w-5 rounded border-gray-300"
                      style={{ accentColor: '#1B4332' }}
                    />
                    <span className="text-sm text-[#212529]">{opt.label}</span>
                  </div>
                  {opt.extra_price > 0 && (
                    <span className="text-sm font-medium text-gray-500">+₹{opt.extra_price}</span>
                  )}
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Quantity */}
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

        {/* Special Request */}
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
          onClick={handleConfirm}
          className="w-full rounded-xl py-4 text-center text-base font-bold text-white transition-colors hover:opacity-90 active:scale-[0.98]"
          style={{ backgroundColor: '#28A745' }}
        >
          Add to Order — ₹{total}
        </button>
      </div>
    </div>
  );
}
