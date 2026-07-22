"use client";

import { useEffect, useState } from "react";
import { AuditLog, adminApi } from "@/lib/api";
import { EmptyRow, ErrorBox, Panel, fmtDate, td, th } from "@/components/ui";

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditLog[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi
      .auditLogs(200)
      .then(setLogs)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load audit log."),
      );
  }, []);

  return (
    <>
      {error && <ErrorBox message={error} />}
      <Panel
        title="Admin audit log"
        subtitle="Append-only record of every approve / reject / unlock action. Newest first, last 200."
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>When</th>
              <th className={th}>Actor</th>
              <th className={th}>Action</th>
              <th className={th}>Target</th>
              <th className={th}>Detail</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {logs === null && <EmptyRow colSpan={5}>Loading…</EmptyRow>}
            {logs?.length === 0 && <EmptyRow colSpan={5}>No admin actions recorded yet.</EmptyRow>}
            {logs?.map((l) => (
              <tr key={l.id}>
                <td className={`${td} whitespace-nowrap text-slate-600`}>
                  {fmtDate(l.created_at)}
                </td>
                <td className={`${td} font-medium`}>{l.actor_username ?? "—"}</td>
                <td className={`${td} font-mono text-xs`}>{l.action}</td>
                <td className={`${td} font-mono text-xs text-slate-600`}>
                  {l.target_type ?? "—"}
                  {l.target_id ? ` ${l.target_id.slice(0, 8)}…` : ""}
                </td>
                <td className={`${td} font-mono text-xs text-slate-600`}>
                  {l.detail ? JSON.stringify(l.detail) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
