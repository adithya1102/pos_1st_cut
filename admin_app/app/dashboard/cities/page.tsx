"use client";

import { useCallback, useEffect, useState } from "react";
import { City, TransportModeDef, adminApi } from "@/lib/api";
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
  // The mode CATALOG. The grid renders one checkbox per entry, so adding a
  // ninth mode server-side needs no change here at all.
  const [modeDefs, setModeDefs] = useState<TransportModeDef[]>([]);
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
    // Failure is non-fatal: an empty catalog renders no mode columns, which
    // reads as "not configured yet" rather than taking the page down.
    adminApi.transportModes().then(setModeDefs, () => setModeDefs([]));
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

  /**
   * Toggle ONE mode for ONE city (migration 030).
   *
   * Saves immediately on tick rather than behind a Save button: each is one
   * boolean, instantly reversible, and a staged grid would be a second thing to
   * forget to press.
   *
   * Optimistic — the checkbox repaints before the request lands, then `load()`
   * reconciles. On failure the reload restores the server's value, so the UI
   * can never sit showing a setting the server rejected.
   */
  const toggleMode = (city: City, code: string, enabled: boolean) => {
    setBusyId(city.id);
    setError(null);
    setCities((prev) =>
      prev?.map((c) =>
        c.id === city.id ? { ...c, modes: { ...c.modes, [code]: enabled } } : c,
      ) ?? prev,
    );
    adminApi
      .setCityMode(city.id, code, enabled)
      .then(
        (res) => {
          const label = modeDefs.find((m) => m.code === code)?.label ?? code;
          setNotice(
            `${res.name}: ${label} ${enabled ? "enabled" : "disabled"}. ` +
              "Customers see this on their next outlet load — no app update needed.",
          );
          return load();
        },
        (err: unknown) => {
          setError(
            err instanceof Error ? err.message : "Could not update that mode.",
          );
          return load();
        },
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
          "name already belongs to another city — merging two cities is a separate operation. " +
          "Travel modes decide what customers see at checkout: ticking one adds that chip for " +
          "every outlet in the city, on phones that are already installed — no app update. " +
          "Modes marked ·t ask the customer for an arrival time instead of their location. " +
          "The list of modes comes from the server, so a new one appears here on its own." +
          (pending > 0 ? ` ${pending} awaiting review.` : "")
        }
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>City</th>
              <th className={th}>Status</th>
              <th className={th}>Travel modes</th>
              <th className={th}>Requested by</th>
              <th className={th}>Added</th>
              <th className={th}>Decided</th>
              <th className={th}>Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {cities === null && <EmptyRow colSpan={8}>Loading…</EmptyRow>}
            {cities?.length === 0 && (
              <EmptyRow colSpan={8}>No cities yet.</EmptyRow>
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
                <td className={td}>
                  <ModeGrid
                    city={c}
                    defs={modeDefs}
                    disabled={busyId === c.id}
                    onToggle={(code, on) => toggleMode(c, code, on)}
                  />
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

/**
 * One checkbox per mode in the CATALOG — not per mode in a hardcoded list.
 *
 * This is the whole extensibility claim of migration 030 made concrete: `defs`
 * comes from `GET /admin/transport-modes`, so a ninth mode inserted into
 * `transport_modes` renders here on the next page load with no edit to this
 * file, no rebuild and no deploy.
 *
 * A mode absent from `city.modes` falls back to the catalog's `default_enabled`
 * — the same "absent means default" rule the backend read path uses, mirrored
 * here so the checkbox never shows something the server would disagree with.
 */
function ModeGrid({
  city,
  defs,
  disabled,
  onToggle,
}: {
  city: City;
  defs: TransportModeDef[];
  disabled: boolean;
  onToggle: (code: string, enabled: boolean) => void;
}) {
  if (defs.length === 0) {
    return (
      <span className="text-xs text-slate-400">
        No modes configured — run migration 030.
      </span>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-1">
      {defs.map((m) => {
        const on = city.modes?.[m.code] ?? m.default_enabled;
        return (
          <label
            key={m.code}
            className="flex items-center gap-1.5 text-xs text-slate-700"
            // Declared-arrival modes ask the customer for a time instead of a
            // location, which is worth knowing before switching one on.
            title={
              m.uses_declared_arrival
                ? `${m.label}: customer states an arrival time (no GPS)`
                : `${m.label}: travel estimated from the customer's location`
            }
          >
            <input
              type="checkbox"
              data-mode={m.code}
              checked={on}
              disabled={disabled}
              onChange={(e) => onToggle(m.code, e.target.checked)}
            />
            {m.label}
            {m.uses_declared_arrival && (
              <span className="text-slate-400">·t</span>
            )}
          </label>
        );
      })}
    </div>
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
