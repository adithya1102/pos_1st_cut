"use client";

import { useCallback, useEffect, useState } from "react";
import { City, adminApi } from "@/lib/api";
import {
  Button,
  EmptyRow,
  ErrorBox,
  Panel,
  fmtDate,
  td,
  th,
} from "@/components/ui";

/**
 * Canonical city list + the new-city request queue (migration 013).
 *
 * Deliberately the same shape as the outlet verification queue: pending rows
 * first, approve/reject in place, each decision audited server-side. Owners can
 * no longer type a city freehand at signup — they pick from `active` rows here,
 * or file a request that lands in this queue.
 */
export default function CitiesPage() {
  const [cities, setCities] = useState<City[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(
    () =>
      adminApi.cities().then(
        (data) => {
          setCities(data);
          setError(null);
        },
        (err: unknown) =>
          setError(err instanceof Error ? err.message : "Failed to load cities."),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Rename is inline rather than a modal: it edits one short string, and the
  // list around it is the context that makes a collision obvious.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const startRename = (city: City) => {
    setEditingId(city.id);
    setDraftName(city.name);
    setError(null);
    setNotice(null);
  };

  const submitRename = (city: City) => {
    const next = draftName.trim();
    if (next.length < 2) {
      setError("City name must be at least 2 characters.");
      return;
    }
    if (next === city.name) {
      setEditingId(null);
      return;
    }
    setBusyId(city.id);
    setError(null);
    adminApi
      .renameCity(city.id, next)
      .then(
        (res) => {
          setEditingId(null);
          // Say how many outlets moved. outlets.city is a denormalised string,
          // so a rename genuinely rewrites those rows — surfacing the count
          // makes the blast radius visible instead of implied.
          setNotice(
            `Renamed "${res.previous_name}" to "${res.name}". ` +
              (res.outlets_updated === 1
                ? "1 outlet updated."
                : `${res.outlets_updated} outlets updated.`),
          );
          return load();
        },
        (err: unknown) =>
          // A 409 here is the merge guard, and its server message already
          // explains why — surface it verbatim rather than flattening it.
          setError(
            err instanceof Error ? err.message : "Could not rename the city.",
          ),
      )
      .finally(() => setBusyId(null));
  };

  const decide = (city: City, approve: boolean) => {
    setBusyId(city.id);
    const call = approve
      ? adminApi.approveCity(city.id)
      : adminApi.rejectCity(city.id);
    call
      .then(
        () => load(),
        (err: unknown) =>
          setError(
            err instanceof Error ? err.message : "Could not update the city.",
          ),
      )
      .finally(() => setBusyId(null));
  };

  const pending = cities?.filter((c) => c.status === "pending").length ?? 0;

  return (
    <>
      {error && <ErrorBox message={error} />}
      {notice && (
        <div className="rounded border border-green-200 bg-green-50 p-3 text-sm text-slate-700">
          {notice}
        </div>
      )}
      <Panel
        title="Cities"
        subtitle={
          "The canonical list owners choose from at signup. Approving a requested city makes it " +
          "selectable for future signups; it does not rewrite any existing outlet's city. " +
          "Renaming DOES rewrite every outlet holding the old name, and is refused if the new " +
          "name already belongs to another city — merging two cities is a separate operation." +
          (pending > 0 ? ` ${pending} awaiting review.` : "")
        }
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>City</th>
              <th className={th}>Status</th>
              <th className={th}>Requested by</th>
              <th className={th}>Added</th>
              <th className={th}>Decided</th>
              <th className={th}>Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {cities === null && <EmptyRow colSpan={6}>Loading…</EmptyRow>}
            {cities?.length === 0 && (
              <EmptyRow colSpan={6}>No cities yet.</EmptyRow>
            )}
            {cities?.map((c) => (
              <tr
                key={c.id}
                className={c.status === "pending" ? "bg-amber-50/50" : undefined}
              >
                <td className={`${td} font-medium`}>
                  {editingId === c.id ? (
                    <input
                      className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                      value={draftName}
                      autoFocus
                      disabled={busyId === c.id}
                      onChange={(e) => setDraftName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") submitRename(c);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                    />
                  ) : (
                    c.name
                  )}
                </td>
                <td className={td}>
                  <CityStatusBadge status={c.status} />
                </td>
                {/* Null for the seeded cities — nobody requested those. */}
                <td className={`${td} text-slate-600`}>
                  {c.requested_by_outlet_name ?? "—"}
                </td>
                <td className={`${td} text-slate-600`}>{fmtDate(c.created_at)}</td>
                <td className={`${td} text-slate-600`}>
                  {c.decided_at ? fmtDate(c.decided_at) : "—"}
                </td>
                <td className={td}>
                  <div className="flex gap-2">
                    {editingId === c.id ? (
                      <>
                        <Button
                          disabled={busyId === c.id}
                          onClick={() => submitRename(c)}
                        >
                          Save
                        </Button>
                        <Button
                          variant="default"
                          disabled={busyId === c.id}
                          onClick={() => setEditingId(null)}
                        >
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <>
                        {c.status === "pending" && (
                          <>
                            <Button
                              disabled={busyId === c.id}
                              onClick={() => decide(c, true)}
                            >
                              Approve
                            </Button>
                            <Button
                              variant="danger"
                              disabled={busyId === c.id}
                              onClick={() => decide(c, false)}
                            >
                              Reject
                            </Button>
                          </>
                        )}
                        {c.status === "rejected" && (
                          <Button
                            disabled={busyId === c.id}
                            onClick={() => decide(c, true)}
                          >
                            Approve
                          </Button>
                        )}
                        {/* Rename is offered for every status: a misspelling is
                            worth fixing whether or not the city is live. */}
                        <Button
                          variant="default"
                          disabled={busyId === c.id}
                          onClick={() => startRename(c)}
                        >
                          Rename
                        </Button>
                      </>
                    )}
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

function CityStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: "bg-emerald-100 text-emerald-800",
    pending: "bg-amber-100 text-amber-800",
    rejected: "bg-rose-100 text-rose-800",
  };
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
        styles[status] ?? "bg-slate-100 text-slate-600"
      }`}
    >
      {status}
    </span>
  );
}
