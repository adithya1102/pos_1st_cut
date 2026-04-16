'use client';

import { OrderStatus } from '@/lib/types';

const STEPS: { key: OrderStatus; label: string }[] = [
  { key: 'pending', label: 'Received' },
  { key: 'confirmed', label: 'Confirmed' },
  { key: 'in_kitchen', label: 'Preparing' },
  { key: 'ready', label: 'Ready' },
  { key: 'served', label: 'Served' },
];

const STATUS_ORDER: OrderStatus[] = [
  'pending',
  'confirmed',
  'in_kitchen',
  'ready',
  'served',
  'completed',
];

function getStepIndex(status: OrderStatus): number {
  const idx = STATUS_ORDER.indexOf(status);
  return idx === -1 ? 0 : idx;
}

interface ProgressBarProps {
  status: OrderStatus;
}

export default function ProgressBar({ status }: ProgressBarProps) {
  if (status === 'cancelled') {
    return (
      <div className="flex items-center justify-center rounded-xl bg-red-500/10 p-4">
        <span className="text-sm font-medium text-[#ef4444]">Order was cancelled</span>
      </div>
    );
  }

  const currentIndex = getStepIndex(status);

  return (
    <div className="px-2">
      <div className="flex items-center justify-between">
        {STEPS.map((step, i) => {
          const stepIdx = getStepIndex(step.key);
          const isCompleted = currentIndex > stepIdx;
          const isCurrent = currentIndex === stepIdx;
          const isActive = isCompleted || isCurrent;

          return (
            <div key={step.key} className="flex flex-1 items-center">
              {/* Step circle */}
              <div className="flex flex-col items-center">
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold transition-all ${
                    isCompleted
                      ? 'bg-[#22c55e] text-white'
                      : isCurrent
                      ? 'bg-[#f97316] text-white ring-4 ring-[#f97316]/30'
                      : 'bg-slate-700 text-slate-500'
                  }`}
                >
                  {isCompleted ? '✓' : i + 1}
                </div>
                <span
                  className={`mt-2 text-[10px] font-medium ${
                    isActive ? 'text-[#f8fafc]' : 'text-slate-600'
                  }`}
                >
                  {step.label}
                </span>
              </div>

              {/* Connector line */}
              {i < STEPS.length - 1 && (
                <div className="mx-1 h-0.5 flex-1">
                  <div
                    className={`h-full rounded-full transition-all ${
                      currentIndex > stepIdx ? 'bg-[#22c55e]' : 'bg-slate-700'
                    }`}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
