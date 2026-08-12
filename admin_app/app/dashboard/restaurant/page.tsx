"use client";

import { useCallback, useEffect, useState } from "react";
import { RestaurantGroup, adminApi } from "@/lib/api";
import {
  Button,
  ErrorBox,
  Panel,
  StatusBadge,
  td,
  th,
} from "@/components/ui";

const WINDOWS = [7, 30, 90] as const;

function rupees(n: number): string {
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/** "Tue, 12 Aug 2026" from an ISO "YYYY-MM-DD", without pulling in a date lib.
 *  Parsed as UTC noon so a timezone shift cannot roll the label to the day
 *  before — the server already decided which day this is. */
function dayLabel(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/**
 * Orders grouped RESTAURANT -> DAY -> TIME.
 *
 * A different view of the rows the Orders tab already lists — no new schema
 * behind it, just customer_orders joined to outlets and grouped. Orders stays
 * as it is: a flat per-sale log answering "what sold". This answers "how is
 * each restaurant doing, day by day", which a flat list buries.
 *
 * Accordion rather than a tree table: at two levels of nesting a table needs
 * either indentation that breaks column alignment or a column that means
 * something different per row. Collapsing sections keeps one restaurant's day
 * legible without scrolling past every other restaurant's.
 *
 * Windowed, not paginated — see the endpoint's own note: page 2 of a flat list
 * can cut a restaurant's days in half and render a group that looks complete.
 */
export default function RestaurantPage() {
  const [groups, setGroups] = useState<RestaurantGroup[] | null>(null);
  const [days, setDays] = useState<number>(30);
  const [error, setError] = useState<string | null>(null);
  const [openOutlets, setOpenOutlets] = useState<Set<string>>(new Set());
  const [openDays, setOpenDays] = useState<Set<string>>(new Set());

  const load = useCallback(
    (window: number) =>
      adminApi.ordersByRestaurant(window).then(
        (data) => {
          setGroups(data);
          setError(null);
        },
        (err: unknown) =>
          setError(
            err instanceof Error ? err.message : "Failed to load restaurants.",
          ),
      ),
    [],
  );

  useEffect(() => {
    load(days);
  }, [load, days]);

  function toggle(set: Set<string>, key: string): Set<string> {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  }

  const totalOrders = (groups ?? []).reduce((s, g) => s + g.order_count, 0);

  return (
    <Panel
      title="Restaurant"
      subtitle={
        groups === null
          ? "Loading…"
          : `${groups.length} restaurant${groups.length === 1 ? "" : "s"} · ` +
            `${totalOrders} order${totalOrders === 1 ? "" : "s"} in the last ${days} days`
      }
      actions={
        <div className="flex gap-1">
          {WINDOWS.map((w) => (
            <Button
              key={w}
              onClick={() => setDays(w)}
              variant={days === w ? "primary" : "default"}
            >
              {w}d
            </Button>
          ))}
        </div>
      }
    >
      {error && <ErrorBox message={error} />}

      {groups !== null && groups.length === 0 && !error && (
        <p className="px-4 py-6 text-sm text-slate-500">
          No orders in the last {days} days.
        </p>
      )}

      <div className="divide-y divide-slate-200">
        {(groups ?? []).map((g) => {
          const outletKey = g.outlet_id ?? "__unassigned__";
          const outletOpen = openOutlets.has(outletKey);
          const where = [g.locality, g.city].filter(Boolean).join(", ");

          return (
            <div key={outletKey}>
              {/* ---- level 1: restaurant ---- */}
              <button
                type="button"
                onClick={() => setOpenOutlets((s) => toggle(s, outletKey))}
                className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-slate-50"
              >
                <div>
                  <div className="font-medium text-slate-900">
                    {g.outlet_name ?? "Unassigned outlet"}
                  </div>
                  {where && (
                    <div className="text-xs text-slate-500">{where}</div>
                  )}
                </div>
                <div className="flex items-center gap-4 text-sm text-slate-600">
                  <span>
                    {g.order_count} order{g.order_count === 1 ? "" : "s"}
                  </span>
                  <span className="font-medium text-slate-900">
                    {rupees(g.total_amount)}
                  </span>
                  <span className="text-slate-400">
                    {outletOpen ? "▾" : "▸"}
                  </span>
                </div>
              </button>

              {/* ---- level 2: day ---- */}
              {outletOpen && (
                <div className="bg-slate-50/60 pl-4">
                  {g.days.map((d) => {
                    const dayKey = `${outletKey}|${d.day}`;
                    const dayOpen = openDays.has(dayKey);
                    return (
                      <div
                        key={dayKey}
                        className="border-t border-slate-200"
                      >
                        <button
                          type="button"
                          onClick={() => setOpenDays((s) => toggle(s, dayKey))}
                          className="flex w-full items-center justify-between px-4 py-2 text-left hover:bg-slate-100"
                        >
                          <span className="text-sm text-slate-700">
                            {dayLabel(d.day)}
                          </span>
                          <span className="flex items-center gap-4 text-xs text-slate-600">
                            <span>
                              {d.order_count} order
                              {d.order_count === 1 ? "" : "s"}
                            </span>
                            <span className="font-medium">
                              {rupees(d.total_amount)}
                            </span>
                            <span className="text-slate-400">
                              {dayOpen ? "▾" : "▸"}
                            </span>
                          </span>
                        </button>

                        {/* ---- level 3: time ---- */}
                        {dayOpen && (
                          <div className="overflow-x-auto bg-white">
                            <table className="w-full min-w-[560px]">
                              <thead>
                                <tr className="border-y border-slate-200">
                                  <th className={th}>Time</th>
                                  <th className={th}>Status</th>
                                  <th className={th}>Code</th>
                                  <th className={th}>Items</th>
                                  <th className={th}>Amount</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-100">
                                {d.orders.map((o) => (
                                  <tr key={o.order_id}>
                                    <td className={`${td} font-mono`}>
                                      {o.time}
                                    </td>
                                    <td className={td}>
                                      <StatusBadge status={o.status} />
                                    </td>
                                    <td className={`${td} font-mono`}>
                                      {o.pickup_code ?? "—"}
                                    </td>
                                    <td className={td}>{o.item_count}</td>
                                    <td className={td}>
                                      {rupees(o.total_amount)}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
