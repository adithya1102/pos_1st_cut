"use client";

import { useCallback, useEffect, useState } from "react";
import { Outlet, adminApi } from "@/lib/api";
import { Button, EmptyRow, ErrorBox, Panel, fmtDate, td, th } from "@/components/ui";

export default function PendingQueuePage() {
  const [outlets, setOutlets] = useState<Outlet[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Promise-callback shape on purpose: every setState lives inside a .then/.catch
  // callback, so calling load() from an effect does not set state synchronously
  // (react-hooks/set-state-in-effect).
  const load = useCallback(
    () =>
      adminApi.pendingOutlets().then(
        (data) => {
          setOutlets(data);
          setError(null);
        },
        (err: unknown) =>
          setError(err instanceof Error ? err.message : "Failed to load pending outlets."),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  async function decide(outlet: Outlet, approve: boolean) {
    const verb = approve ? "Approve" : "Reject";
    // Both actions are audited and cross-outlet — confirm before firing.
    const reason = window.prompt(
      `${verb} "${outlet.location_name}"?\n\nOptional reason (recorded in the audit log):`,
      "",
    );
    if (reason === null) return; // cancelled

    setBusyId(outlet.id);
    try {
      if (approve) await adminApi.approveOutlet(outlet.id, reason || undefined);
      else await adminApi.rejectOutlet(outlet.id, reason || undefined);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${verb} failed.`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      {error && <ErrorBox message={error} />}
      <Panel
        title="Pending restaurants"
        subtitle="Outlets awaiting platform verification. Approving sets verification_status to 'active'."
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>Outlet</th>
              <th className={th}>Organization</th>
              <th className={th}>City</th>
              <th className={th}>Created</th>
              <th className={th}>Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {outlets === null && <EmptyRow colSpan={5}>Loading…</EmptyRow>}
            {outlets?.length === 0 && (
              <EmptyRow colSpan={5}>Nothing pending. Queue is clear.</EmptyRow>
            )}
            {outlets?.map((o) => (
              <tr key={o.id}>
                <td className={`${td} font-medium`}>{o.location_name}</td>
                <td className={`${td} text-slate-600`}>{o.organization_name ?? "—"}</td>
                <td className={`${td} text-slate-600`}>{o.city ?? "—"}</td>
                <td className={`${td} text-slate-600`}>{fmtDate(o.created_at)}</td>
                <td className={td}>
                  <div className="flex gap-2">
                    <Button
                      variant="primary"
                      disabled={busyId === o.id}
                      onClick={() => decide(o, true)}
                    >
                      Approve
                    </Button>
                    <Button
                      variant="danger"
                      disabled={busyId === o.id}
                      onClick={() => decide(o, false)}
                    >
                      Reject
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
