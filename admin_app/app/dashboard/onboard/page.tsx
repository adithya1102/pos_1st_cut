"use client";

import { useEffect, useState } from "react";
import { ApiError, City, RegisterOutletResult, adminApi } from "@/lib/api";
import { Button, ErrorBox } from "@/components/ui";

const inputCls =
  "w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-slate-900 focus:outline-none";
const VPA_RE = /^[^@\s]+@[^@\s]+$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// Sentinel <option> value. Deliberately not a plausible city name, so it can
// never collide with a real entry from the cities list.
const REQUEST_NEW_CITY = "__request_new_city__";

/**
 * Admin-assisted onboarding. Sets up a restaurant on behalf of a non-technical
 * owner via the same public /register flow the owner_app self-signup uses — the
 * new outlet lands as pending_verification, then appears in the pending queue.
 *
 * The field set is kept in step with RegisterIn deliberately. This form
 * previously omitted locality, phone_number and email — all three REQUIRED
 * server-side — so every submission was rejected 422 before it reached the
 * queue. Anything added to RegisterIn must be added here too.
 */
export default function OnboardPage() {
  const [form, setForm] = useState({
    restaurant_name: "",
    city: "",
    requested_city: "",
    locality: "",
    phone_number: "",
    email: "",
    latitude: "",
    longitude: "",
    username: "",
    password: "",
    upi_id: "",
  });
  const [cities, setCities] = useState<City[] | null>(null);
  const [citiesError, setCitiesError] = useState<string | null>(null);
  // Mirrors owner_app's signup screen (_requestingNewCity there): the dropdown
  // carries a sentinel entry that swaps in a text input, rather than allowing
  // free text alongside the list. Free-text city is what let
  // "Bangalore"/"Bengaluru" diverge in the first place.
  const [requestingNewCity, setRequestingNewCity] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegisterOutletResult | null>(null);

  // A dropdown of APPROVED cities rather than free text: /register only accepts
  // a city already active in the canonical list, so a typed one would be
  // rejected 422 with nothing on screen explaining why.
  useEffect(() => {
    adminApi
      .cities("active")
      .then(setCities)
      .catch(() => {
        setCities([]);
        setCitiesError("Could not load cities.");
      });
  }, []);

  function set(key: keyof typeof form, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function validate(): string | null {
    if (form.restaurant_name.trim().length < 2) return "Enter the restaurant name.";
    if (requestingNewCity) {
      const asked = form.requested_city.trim();
      if (asked.length < 2) return "Enter the new city's name.";
      if (asked.length > 80) return "City name is too long (max 80 characters).";
      // NOT blocked on an existing name: the admin route reuses the existing
      // row (case-insensitively) rather than duplicating it, so typing a city
      // that already exists is a no-op that still onboards the outlet
      // correctly. `cities` guarantees this with a unique index on lower(name).
    } else if (!form.city.trim()) {
      return "Select the city.";
    }
    if (form.locality.trim().length < 2) return "Enter the area / locality.";
    if (form.phone_number.trim().length < 6) return "Enter a valid contact phone number.";
    if (!EMAIL_RE.test(form.email.trim())) return "Enter a valid owner email.";
    if (!VPA_RE.test(form.upi_id.trim())) return "Enter a valid UPI ID (name@bank).";
    if (form.username.trim().length < 3) return "Username must be at least 3 characters.";
    if (form.password.length < 8) return "Password must be at least 8 characters.";

    // Coordinates are required BY THIS FORM, not by the server. An outlet with
    // no pin cannot be shown on a map, so the customer app hides its "Open in
    // Maps" button and can compute no distance to it — the restaurant is
    // effectively unverifiable to a customer deciding whether to walk there.
    for (const k of ["latitude", "longitude"] as const) {
      const raw = form[k].trim();
      if (!raw) return `Enter the ${k}.`;
      if (Number.isNaN(Number(raw))) return `Invalid ${k}.`;
    }
    const lat = Number(form.latitude);
    const lng = Number(form.longitude);
    if (lat < -90 || lat > 90) return "Latitude must be between -90 and 90.";
    if (lng < -180 || lng > 180) return "Longitude must be between -180 and 180.";
    return null;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      // A new city typed by an ADMIN is created active up front, then the
      // outlet registers against it by name like any other. That is why this
      // sends `city` and never `requested_city`: `requested_city` means "file a
      // pending request", which is owner_app's self-service path and is not
      // what an admin — the approval authority — is doing here.
      //
      // Two calls rather than one, deliberately: /register is unauthenticated,
      // so a "create this city as active" flag on it would let anyone extend
      // the canonical list. The privilege lives on the SUPER_ADMIN-gated route.
      let cityName = form.city.trim();
      if (requestingNewCity) {
        const created = await adminApi.createCity(form.requested_city.trim());
        // Use the row's canonical spelling, not what was typed — if the city
        // already existed as "Kochi" and "kochi" was entered, the outlet must
        // carry the canonical one.
        cityName = created.name;
      }

      const res = await adminApi.registerOutlet({
        restaurant_name: form.restaurant_name.trim(),
        city: cityName,
        locality: form.locality.trim(),
        phone_number: form.phone_number.trim(),
        email: form.email.trim().toLowerCase(),
        latitude: Number(form.latitude),
        longitude: Number(form.longitude),
        username: form.username.trim(),
        password: form.password,
        upi_id: form.upi_id.trim(),
      });
      setResult(res);
      setForm({
        restaurant_name: "", city: "", requested_city: "", locality: "",
        phone_number: "", email: "",
        latitude: "", longitude: "", username: "", password: "", upi_id: "",
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 409 ? "That username or email is already registered."
          : err.status === 429 ? "Too many attempts — try again shortly."
          : err.message,
        );
      } else {
        setError("Could not register. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <h1 className="text-lg font-semibold">Onboard a restaurant</h1>
      <p className="text-sm text-slate-500">
        Creates the outlet (pending verification) and an owner login. It appears
        in the pending queue for approval before it goes live to customers.
      </p>

      {result && (
        <div className="rounded border border-green-200 bg-green-50 p-4 text-sm">
          <p className="font-medium text-green-700">Registered ✓</p>
          <p className="mt-1 text-slate-600">
            Owner <b>{result.username}</b> · status {result.verification_status}.
            Approve it from the pending queue.
          </p>
        </div>
      )}

      {error && <ErrorBox message={error} />}

      <form onSubmit={submit} className="space-y-3">
        <Field label="Restaurant name">
          <input className={inputCls} value={form.restaurant_name}
            onChange={(e) => set("restaurant_name", e.target.value)} />
        </Field>

        <Field label="City">
          <select
            className={inputCls}
            value={requestingNewCity ? REQUEST_NEW_CITY : form.city}
            disabled={cities === null}
            onChange={(e) => {
              const v = e.target.value;
              if (v === REQUEST_NEW_CITY) {
                setRequestingNewCity(true);
                set("city", "");
              } else {
                setRequestingNewCity(false);
                set("requested_city", "");
                set("city", v);
              }
            }}
          >
            <option value="">
              {cities === null ? "Loading cities…" : "Select a city"}
            </option>
            {(cities ?? []).map((c) => (
              <option key={c.id} value={c.name}>{c.name}</option>
            ))}
            <option value={REQUEST_NEW_CITY}>+ Add a new city…</option>
          </select>
          {citiesError && (
            <span className="text-xs text-red-600">{citiesError}</span>
          )}
        </Field>

        {requestingNewCity && (
          <Field label="New city name">
            <input
              className={inputCls}
              value={form.requested_city}
              autoFocus
              placeholder="e.g. Coimbatore"
              onChange={(e) => set("requested_city", e.target.value)}
            />
            <span className="text-xs text-slate-500">
              Added as <b>active</b> immediately and selectable by everyone from
              then on — you are the approval authority, so there is no pending
              step. If the city already exists in any spelling, that entry is
              reused rather than duplicated.
            </span>
          </Field>
        )}

        <Field label="Area / locality">
          <input className={inputCls} placeholder="e.g. Koramangala"
            value={form.locality}
            onChange={(e) => set("locality", e.target.value)} />
          <span className="text-xs text-slate-500">
            Shown to customers as “{form.restaurant_name || "Restaurant"} ·{" "}
            {form.locality || "Area"}”, and used to catch duplicate listings.
          </span>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Latitude">
            <input className={inputCls} placeholder="12.9352" value={form.latitude}
              onChange={(e) => set("latitude", e.target.value)} />
          </Field>
          <Field label="Longitude">
            <input className={inputCls} placeholder="77.6245" value={form.longitude}
              onChange={(e) => set("longitude", e.target.value)} />
          </Field>
        </div>
        <p className="text-xs text-slate-500">
          Required here: without coordinates the customer app cannot show this
          restaurant on a map or work out how far away it is.
        </p>

        <Field label="Contact phone">
          <input className={inputCls} value={form.phone_number}
            onChange={(e) => set("phone_number", e.target.value)} />
        </Field>
        <Field label="Owner email">
          <input className={inputCls} type="email" placeholder="owner@example.com"
            value={form.email}
            onChange={(e) => set("email", e.target.value)} />
          <span className="text-xs text-slate-500">
            Used for the owner’s password recovery.
          </span>
        </Field>
        <Field label="Restaurant UPI ID">
          <input className={inputCls} placeholder="name@bank" value={form.upi_id}
            onChange={(e) => set("upi_id", e.target.value)} />
        </Field>
        <Field label="Owner username">
          <input className={inputCls} value={form.username}
            onChange={(e) => set("username", e.target.value)} />
        </Field>
        <Field label="Owner password">
          <input className={inputCls} type="password" value={form.password}
            onChange={(e) => set("password", e.target.value)} />
        </Field>
        <Button type="submit" disabled={busy}>
          {busy ? "Registering…" : "Register restaurant"}
        </Button>
      </form>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}
