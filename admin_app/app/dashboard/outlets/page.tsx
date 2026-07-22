"use client";

import { useCallback, useEffect, useState } from "react";
import { Outlet, VerificationStatus, adminApi } from "@/lib/api";
import {
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

  useEffect(() => {
    load();
  }, [load]);

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
              <th className={th}>Verification</th>
              <th className={th}>Visible</th>
              <th className={th}>Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {outlets === null && <EmptyRow colSpan={6}>Loading…</EmptyRow>}
            {outlets?.length === 0 && <EmptyRow colSpan={6}>No outlets match.</EmptyRow>}
            {outlets?.map((o) => (
              <tr key={o.id}>
                <td className={`${td} font-medium`}>{o.location_name}</td>
                <td className={`${td} text-slate-600`}>{o.organization_name ?? "—"}</td>
                <td className={`${td} text-slate-600`}>{o.city ?? "—"}</td>
                <td className={td}>
                  <StatusBadge status={o.verification_status} />
                </td>
                <td className={`${td} text-slate-600`}>{o.is_visible ? "yes" : "no"}</td>
                <td className={`${td} text-slate-600`}>{fmtDate(o.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
