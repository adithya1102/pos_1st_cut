"use client";

import { useCallback, useEffect, useState } from "react";
import { Outlet, VerificationStatus, adminApi } from "@/lib/api";
import {
  Button,
  EmptyRow,
  ErrorBox,
  Panel,
  StatusBadge,
  fmtDate,
  td,
  th,
} from "@/components/ui";

const FILTERS: { label: string; value: VerificationStatus | "" }[] = [
  { label: "All", value: "" },
  { label: "Pending", value: "pending_verification" },
  { label: "Active", value: "active" },
  { label: "Rejected", value: "rejected" },
];

export default function OutletsPage() {
  const [filter, setFilter] = useState<VerificationStatus | "">("");
  const [outlets, setOutlets] = useState<Outlet[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Promise-callback shape: no synchronous setState in the effect body
  // (react-hooks/set-state-in-effect). On a filter change the previous rows
  // stay up for one round-trip rather than flashing an empty table.
  const load = useCallback(
    () =>
      adminApi.outlets(filter || undefined).then(
        (data) => {
          setOutlets(data);
          setError(null);
        },
        (err: unknown) =>
          setError(err instanceof Error ? err.message : "Failed to load outlets."),
      ),
    [filter],
  );

  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, [load]);

  async function deactivate(o: Outlet) {
    const confirmed = window.confirm(
      `Deactivate "${o.location_name}"?\n\n` +
        `It will be hidden from customers and marked deactivated in the console. ` +
        `All order & event history is retained (this is a soft-delete, not a purge) ` +
        `and it can be reactivated later. The action is audited.`,
    );
    if (!confirmed) return;
    setBusyId(o.id);
    try {
      await adminApi.deactivateOutlet(o.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deactivate failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function reactivate(o: Outlet) {
    setBusyId(o.id);
    try {
      await adminApi.reactivateOutlet(o.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reactivate failed.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      {error && <ErrorBox message={error} />}

      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setFilter(f.value)}
            className={`rounded border px-3 py-1.5 text-sm ${
              filter === f.value
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <Panel
        title="All outlets"
        subtitle="verification_status is the platform gate; is_visible is the owner's own discovery toggle. They are independent."
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>Outlet</th>
              <th className={th}>Organization</th>
              <th className={th}>City</th>
              <th className={th}>Phone</th>
              <th className={th}>Owner login</th>
              <th className={th}>Verification</th>
              <th className={th}>Visible</th>
              <th className={th}>Created</th>
              <th className={th}>Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {outlets === null && <EmptyRow colSpan={8}>Loading…</EmptyRow>}
            {outlets?.length === 0 && <EmptyRow colSpan={8}>No outlets match.</EmptyRow>}
            {outlets?.map((o) => (
              <tr key={o.id} className={o.is_deactivated ? "bg-slate-50/60" : undefined}>
                <td className={`${td} font-medium`}>
                  {/* "{Restaurant Name} · {Locality}". The separator is
                      suppressed entirely when locality is null (outlets
                      predating migration 012) so the cell never renders a
                      dangling "· ". */}
                  {o.location_name}
                  {o.locality && (
                    <span className="text-slate-500 font-normal">
                      {" · "}
                      {o.locality}
                    </span>
                  )}
                  {o.is_deactivated && (
                    <span className="ml-2 inline-block rounded bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600">
                      deactivated
                    </span>
                  )}
                </td>
                <td className={`${td} text-slate-600`}>{o.organization_name ?? "—"}</td>
                <td className={`${td} text-slate-600`}>{o.city ?? "—"}</td>
                {/* Null for outlets that predate migration 009, and for owners
                    who skipped the optional field at signup. */}
                <td className={`${td} font-mono text-xs text-slate-600`}>
                  {o.phone_number ?? "—"}
                </td>
                {/* Username only — enough for support to point someone at
                    /auth/password/forgot, which already works on a username.
                    Null when the outlet has no active staff row yet. */}
                <td className={`${td} font-mono text-xs text-slate-600`}>
                  {o.owner_username ?? "—"}
                </td>
                <td className={td}>
                  <StatusBadge status={o.verification_status} />
                </td>
                <td className={`${td} text-slate-600`}>{o.is_visible ? "yes" : "no"}</td>
                <td className={`${td} text-slate-600`}>{fmtDate(o.created_at)}</td>
                <td className={td}>
                  {o.is_deactivated ? (
                    <Button disabled={busyId === o.id} onClick={() => reactivate(o)}>
                      Reactivate
                    </Button>
                  ) : (
                    <Button
                      variant="danger"
                      disabled={busyId === o.id}
                      onClick={() => deactivate(o)}
                    >
                      Deactivate
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
