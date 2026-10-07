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
 * Why money is owed, in words. The raw values come from
 * customer_orders.refund_reason and are set by the three paths that take
 * payment and then fail to deliver food.
 */
const REFUND_REASON_LABEL: Record<string, string> = {
  order_rejected: "Rejected",
  ttl_abandoned: "Not collected",
  acceptance_expired: "Not accepted",
};

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
  /**
   * Refund-due filter (migration 032).
   *
   * Switches the DATA SOURCE rather than filtering the loaded page. Filtering
   * client-side would only ever search the 50 rows currently on screen, so a
   * refund flagged 200 orders ago would be invisible — which for a list of
   * money owed is the one failure that matters.
   */
  const [refundOnly, setRefundOnly] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(
    (off: number, onlyRefunds: boolean) =>
      (onlyRefunds
        ? adminApi.refundDue(200).then((list) => ({
            // Mapped onto the table's shape so one <tbody> renders both
            // sources. The fields this view does not carry are nulled
            // explicitly rather than faked.
            orders: list.map((r) => ({
              order_id: r.order_id,
              pickup_code: null,
              status: r.status,
              payment_status: r.payment_status,
              created_at: r.created_at,
              customer_name: null,
              customer_phone: r.customer_phone,
              customer_email: null,
              outlet_name: r.outlet_name,
              items: [],
              total_amount: r.total_amount,
              discount_amount: 0,
              promotion_label: null,
              promotion_code: null,
              promotion_discount: null,
              distance_km: null,
              refund_required: true,
              refund_reason: r.refund_reason,
            })) as AdminOrder[],
            total: list.length,
            offset: 0,
          }))
        : adminApi.orders(PAGE, off)
      ).then(
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
    load(0, refundOnly);
  }, [load, refundOnly]);

  /** Record an off-app settlement, then refresh so the row leaves the list. */
  const markRefunded = async (orderId: string) => {
    setBusy(orderId);
    try {
      await adminApi.markRefunded(orderId);
      await load(refundOnly ? 0 : offset, refundOnly);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to mark refunded.");
    } finally {
      setBusy(null);
    }
  };

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE, total);

  return (
    <>
      {error && <ErrorBox message={error} />}
      <Panel
        title="Orders"
        subtitle={
          refundOnly
            ? `Orders where money was taken and no food was delivered, oldest first.` +
              (total ? ` ${total} outstanding.` : " None outstanding.")
            : `Every order across all outlets, newest first.` +
              (total ? ` Showing ${from}–${to} of ${total}.` : "")
        }
      >
        <div className="flex items-center gap-3 border-b border-slate-200 px-4 py-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={refundOnly}
              onChange={(e) => setRefundOnly(e.target.checked)}
              className="h-4 w-4"
            />
            <span className="font-medium">Refund due only</span>
          </label>
          <span className="text-xs text-slate-500">
            Refunds are settled manually, off-app — marking one here records
            that a human did it.
          </span>
        </div>

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
              <th className={th}>Refund</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows === null && <EmptyRow colSpan={10}>Loading…</EmptyRow>}
            {rows?.length === 0 && <EmptyRow colSpan={10}>
                {refundOnly ? "No refunds outstanding." : "No orders yet."}
              </EmptyRow>}
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
                <td className={`${td} whitespace-nowrap`}>
                  {o.refund_required ? (
                    <div className="flex items-center gap-2">
                      <span
                        className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-900"
                        title={o.refund_reason ?? undefined}
                      >
                        {/* The reason is the useful part: a reject, a pickup
                            that timed out, and an unanswered acceptance are
                            three different conversations with the customer. */}
                        {REFUND_REASON_LABEL[o.refund_reason ?? ""] ?? "Due"}
                      </span>
                      <Button
                        disabled={busy === o.order_id}
                        onClick={() => markRefunded(o.order_id)}
                      >
                        {busy === o.order_id ? "…" : "Mark done"}
                      </Button>
                    </div>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Pagination is hidden in refund mode: that endpoint returns one
            bounded list, not a page, so Previous/Next would be dead controls. */}
        {!refundOnly && (
          <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
            <span className="text-xs text-slate-500">
              {total ? `${from}–${to} of ${total}` : ""}
            </span>
            <div className="flex gap-2">
              <Button
                disabled={offset === 0}
                onClick={() => load(Math.max(0, offset - PAGE), refundOnly)}
              >
                Previous
              </Button>
              <Button
                disabled={to >= total}
                onClick={() => load(offset + PAGE, refundOnly)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Panel>
    </>
  );
}
