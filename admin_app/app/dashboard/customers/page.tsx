"use client";

import { useCallback, useEffect, useState } from "react";
import { CustomerRow, adminApi } from "@/lib/api";
import { EmptyRow, ErrorBox, Panel, fmtDate, td, th } from "@/components/ui";

export default function CustomersPage() {
  const [customers, setCustomers] = useState<CustomerRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Same promise-callback shape as the other dashboard pages: every setState
  // sits inside a .then/.catch so calling load() from an effect never sets
  // state synchronously (react-hooks/set-state-in-effect).
  const load = useCallback(
    () =>
      adminApi.customers().then(
        (data) => {
          setCustomers(data);
          setError(null);
        },
        (err: unknown) =>
          setError(err instanceof Error ? err.message : "Failed to load customers."),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      {error && <ErrorBox message={error} />}
      <Panel
        title="Customers"
        subtitle="Every customer who has signed in, across all outlets, newest first. Read-only — there is no edit or delete path from here."
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>Phone</th>
              <th className={th}>Email</th>
              <th className={th}>Name</th>
              <th className={th}>Orders</th>
              <th className={th}>Points</th>
              <th className={th}>Plan</th>
              <th className={th}>Joined</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {customers === null && <EmptyRow colSpan={7}>Loading…</EmptyRow>}
            {customers?.length === 0 && (
              <EmptyRow colSpan={7}>No customers yet.</EmptyRow>
            )}
            {customers?.map((c) => (
              <tr key={c.id}>
                {/* Exactly one of phone/email is null for most rows: OTP
                    customers have no email, Google customers no phone. */}
                <td className={`${td} font-mono text-xs`}>
                  {c.phone_number ?? "—"}
                </td>
                <td className={`${td} text-slate-600`}>{c.email ?? "—"}</td>
                {/* Name is null for anyone who signed in but never supplied one,
                    which is the common case. */}
                <td className={`${td} text-slate-600`}>{c.name ?? "—"}</td>
                <td className={td}>{c.order_count}</td>
                {/* Zero balance shows "—" rather than "0" so the eye skips it,
                    same as the other default-valued columns. */}
                <td className={td}>
                  {c.points_balance > 0 ? c.points_balance : "—"}
                </td>
                <td className={`${td} text-slate-600`}>
                  {c.plan === "Premium" ? (
                    <span
                      className="inline-block rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
                      title={
                        c.premium_until
                          ? `Trial until ${fmtDate(c.premium_until)}`
                          : undefined
                      }
                    >
                      Premium
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className={`${td} text-slate-600`}>{fmtDate(c.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
