"use client";

import { useCallback, useEffect, useState } from "react";
import { LockedOrder, adminApi } from "@/lib/api";
import { Button, EmptyRow, ErrorBox, Panel, fmtDate, td, th } from "@/components/ui";

export default function LockedOrdersPage() {
  const [orders, setOrders] = useState<LockedOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Promise-callback shape on purpose: every setState lives inside a .then/.catch
  // callback, so calling load() from an effect does not set state synchronously
  // (react-hooks/set-state-in-effect).
  const load = useCallback(
    () =>
      adminApi.lockedOrders().then(
        (data) => {
          setOrders(data);
          setError(null);
        },
        (err: unknown) =>
          setError(err instanceof Error ? err.message : "Failed to load locked orders."),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  async function unlock(order: LockedOrder) {
    const confirmed = window.confirm(
      `Unlock order ${order.order_id}?\n\n` +
        `This clears the 3-strike pickup lockout and resets failed_attempts to 0, ` +
        `letting the customer's pickup code be entered again. The action is audited.`,
    );
    if (!confirmed) return;

    setBusyId(order.order_id);
    try {
      await adminApi.unlockOrder(order.order_id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unlock failed.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      {error && <ErrorBox message={error} />}
      <Panel
        title="Locked orders"
        subtitle="Orders locked by 3 failed pickup-code attempts, across all outlets. Lockout is not auto-recoverable in v1 — this is the manual path."
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>Order</th>
              <th className={th}>Outlet</th>
              <th className={th}>Customer</th>
              <th className={th}>Status</th>
              <th className={th}>Attempts</th>
              <th className={th}>Total</th>
              <th className={th}>Created</th>
              <th className={th}>Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {orders === null && <EmptyRow colSpan={8}>Loading…</EmptyRow>}
            {orders?.length === 0 && (
              <EmptyRow colSpan={8}>No locked orders. Nothing to do.</EmptyRow>
            )}
            {orders?.map((o) => (
              <tr key={o.order_id}>
                <td className={`${td} font-mono text-xs`}>{o.order_id.slice(0, 8)}…</td>
                <td className={`${td} text-slate-600`}>{o.outlet_name ?? "—"}</td>
                <td className={`${td} text-slate-600`}>{o.customer_phone ?? "—"}</td>
                <td className={`${td} text-slate-600`}>{o.status}</td>
                <td className={td}>{o.failed_attempts}</td>
                <td className={td}>₹{o.total_amount.toFixed(2)}</td>
                <td className={`${td} text-slate-600`}>{fmtDate(o.created_at)}</td>
                <td className={td}>
                  <Button
                    variant="primary"
                    disabled={busyId === o.order_id}
                    onClick={() => unlock(o)}
                  >
                    Unlock
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
