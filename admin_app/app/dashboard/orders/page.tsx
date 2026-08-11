"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminOrder, adminApi } from "@/lib/api";
import {
  Button,
  EmptyRow,
  ErrorBox,
  Panel,
  fmtDate,
  td,
  th,
} from "@/components/ui";

const PAGE = 50;

/**
 * Per-ORDER log, across every outlet.
 *
 * Deliberately a separate page from Customers rather than more columns on it:
 * that table is one row per person and answers "who are our customers", this is
 * one row per sale and answers "what was ordered, by whom, for how much". The
 * Customers tab is untouched.
 *
 * Paginated rather than capped. Customers takes a bare limit=200 and silently
 * hides everything past it — survivable for a directory, not for a log that
 * grows with every sale.
 */
export default function OrdersPage() {
  const [rows, setRows] = useState<AdminOrder[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (off: number) =>
      adminApi.orders(PAGE, off).then(
        (page) => {
          setRows(page.orders);
          setTotal(page.total);
          setOffset(page.offset);
          setError(null);
        },
        (err: unknown) =>
          setError(err instanceof Error ? err.message : "Failed to load orders."),
      ),
    [],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE, total);

  return (
    <>
      {error && <ErrorBox message={error} />}
      <Panel
        title="Orders"
        subtitle={
          `Every order across all outlets, newest first.` +
          (total ? ` Showing ${from}–${to} of ${total}.` : "")
        }
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>When</th>
              <th className={th}>Customer</th>
              <th className={th}>Outlet</th>
              <th className={th}>Dishes</th>
              <th className={th}>Code</th>
              <th className={th}>Status</th>
              <th className={th}>Promotion</th>
              <th className={th}>Distance</th>
              <th className={th}>Paid</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows === null && <EmptyRow colSpan={9}>Loading…</EmptyRow>}
            {rows?.length === 0 && <EmptyRow colSpan={9}>No orders yet.</EmptyRow>}
            {rows?.map((o) => (
              <tr key={o.order_id}>
                <td className={`${td} whitespace-nowrap text-slate-600`}>
                  {fmtDate(o.created_at)}
                </td>
                <td className={td}>
                  {/* All three are nullable: OTP customers have no email,
                      Google customers no phone, deleted accounts neither. */}
                  <div className="font-medium">{o.customer_name ?? "—"}</div>
                  <div className="text-xs text-slate-500">
                    {o.customer_phone ?? o.customer_email ?? "—"}
                  </div>
                </td>
                <td className={`${td} text-slate-600`}>{o.outlet_name ?? "—"}</td>
                <td className={`${td} max-w-xs`}>
                  {o.items.length === 0
                    ? "—"
                    : o.items
                        .map((i) => `${i.quantity}× ${i.name ?? "Item"}`)
                        .join(", ")}
                </td>
                <td className={td}>
                  {o.pickup_code ? (
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                      {o.pickup_code}
                    </code>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
                <td className={td}>
                  <div>{o.status}</div>
                  <div className="text-xs text-slate-500">{o.payment_status ?? "—"}</div>
                </td>
                <td className={td}>
                  {o.promotion_label ? (
                    <>
                      <div>{o.promotion_label}</div>
                      <div className="text-xs text-slate-500">
                        −₹{(o.promotion_discount ?? 0).toFixed(2)}
                        {o.promotion_code ? ` · ${o.promotion_code}` : ""}
                      </div>
                    </>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
                <td className={`${td} whitespace-nowrap`}>
                  {/* Null means the customer never shared an origin. Rendering
                      "—" rather than 0 keeps "unknown" distinct from "here". */}
                  {o.distance_km === null ? (
                    <span className="text-slate-400">—</span>
                  ) : (
                    `${o.distance_km.toFixed(1)} km`
                  )}
                </td>
                <td className={`${td} whitespace-nowrap font-medium`}>
                  ₹{o.total_amount.toFixed(2)}
                  {o.discount_amount > 0 && (
                    <div className="text-xs font-normal text-slate-500">
                      −₹{o.discount_amount.toFixed(2)} off
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
          <span className="text-xs text-slate-500">
            {total ? `${from}–${to} of ${total}` : ""}
          </span>
          <div className="flex gap-2">
            <Button disabled={offset === 0} onClick={() => load(Math.max(0, offset - PAGE))}>
              Previous
            </Button>
            <Button disabled={to >= total} onClick={() => load(offset + PAGE)}>
              Next
            </Button>
          </div>
        </div>
      </Panel>
    </>
  );
}
