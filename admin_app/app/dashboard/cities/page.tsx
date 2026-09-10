"use client";

import { useCallback, useEffect, useState } from "react";
import { City, CityType, adminApi } from "@/lib/api";
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

  /**
   * Transport profile (migration 029).
   *
   * Saves immediately on change rather than behind a Save button: it is one
   * radio and one checkbox, both instantly reversible, and a staged edit here
   * would mean a second thing to forget to press.
   *
   * Optimistic — the row repaints before the request lands, then `load()`
   * reconciles. On failure the reload puts the old value back, so the UI can
   * never end up showing a setting the server did not accept.
   */
  const saveTransport = (
    city: City,
    patch: { city_type?: CityType; has_train?: boolean },
  ) => {
    setBusyId(city.id);
    setError(null);
    setCities(
      (prev) =>
        prev?.map((c) =>
          c.id === city.id
            ? {
                ...c,
                ...patch,
                // has_metro is derived server-side; mirror the rule locally so
                // the badge does not lag a beat behind the radio.
                has_metro:
                  patch.city_type !== undefined
                    ? patch.city_type === "metro"
                    : c.has_metro,
              }
            : c,
        ) ?? prev,
    );
    adminApi
      .setCityTransport(city.id, patch)
      .then(
        (res) => {
          setNotice(
            `${res.name}: ${CITY_TYPE_LABELS[res.city_type] ?? res.city_type}` +
              `${res.has_metro ? ", Metro on" : ""}` +
              `${res.has_train ? ", Train on" : ""}` +
              ". Customers see this on their next outlet load — no app update needed.",
          );
          return load();
        },
        (err: unknown) => {
          setError(
            err instanceof Error
              ? err.message
              : "Could not update the city's transport profile.",
          );
          // Undo the optimistic paint by re-reading the truth.
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
          "City type and travel modes drive what customers see at checkout: marking a city " +
          "“Metro city” adds the Metro option for every outlet in it, on phones that are " +
          "already installed — no app update. Train is set separately, because a city can have " +
          "a mainline junction and no metro." +
          (pending > 0 ? ` ${pending} awaiting review.` : "")
        }
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>City</th>
              <th className={th}>Status</th>
              <th className={th}>City type</th>
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
                  <CityTypeRadio
                    city={c}
                    disabled={busyId === c.id}
                    onChange={(city_type) => saveTransport(c, { city_type })}
                  />
                </td>
                <td className={td}>
                  <div className="flex flex-col gap-1">
                    {/* Metro is DERIVED from the radio, so it is shown, not
                        toggled — two controls for one fact is how they drift. */}
                    <span className="text-xs text-slate-600">
                      Metro:{" "}
                      <span
                        className={
                          c.has_metro
                            ? "font-medium text-emerald-700"
                            : "text-slate-400"
                        }
                      >
                        {c.has_metro ? "on" : "off"}
                      </span>
                      <span className="text-slate-400"> (from city type)</span>
                    </span>
                    {/* Train is its OWN answer: Madurai is a tier-2 city with a
                        major junction and no metro, and one flag could not say
                        that. */}
                    <label className="flex items-center gap-1.5 text-xs text-slate-600">
                      <input
                        type="checkbox"
                        checked={c.has_train}
                        disabled={busyId === c.id}
                        onChange={(e) =>
                          saveTransport(c, { has_train: e.target.checked })
                        }
                      />
                      Train
                    </label>
                  </div>
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

/** Labels for the radio. Order is the order they render in. */
const CITY_TYPE_LABELS: Record<string, string> = {
  metro: "Metro city",
  tier_1: "Tier 1",
  tier_2: "Tier 2",
  tier_3: "Tier 3",
};

const CITY_TYPES = Object.keys(CITY_TYPE_LABELS) as CityType[];

/**
 * The city-type radio — the control that decides whether customers in this city
 * see the Metro option at checkout.
 *
 * A radio, not a dropdown: four mutually exclusive options, all worth seeing at
 * once, and "which of these is Chennai" is a question you answer by comparing
 * them rather than by opening a menu.
 *
 * `city_type` can arrive null from a backend that has not run migration 029.
 * That renders as nothing selected rather than defaulting to Tier 2, so an
 * un-migrated deployment reads as "unknown" instead of quietly asserting an
 * answer the server never gave.
 */
function CityTypeRadio({
  city,
  disabled,
  onChange,
}: {
  city: City;
  disabled: boolean;
  onChange: (type: CityType) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      {CITY_TYPES.map((type) => (
        <label
          key={type}
          className="flex items-center gap-1.5 text-xs text-slate-700"
        >
          <input
            type="radio"
            // Scoped per city, or every row would share one selection.
            name={`city_type_${city.id}`}
            checked={city.city_type === type}
            disabled={disabled}
            onChange={() => onChange(type)}
          />
          {CITY_TYPE_LABELS[type]}
        </label>
      ))}
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
