"use client";

import { useState } from "react";
import { ApiError, RegisterOutletResult, adminApi } from "@/lib/api";
import { Button, ErrorBox } from "@/components/ui";

const inputCls =
  "w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-slate-900 focus:outline-none";
const VPA_RE = /^[^@\s]+@[^@\s]+$/;

/**
 * Admin-assisted onboarding. Sets up a restaurant on behalf of a non-technical
 * owner via the same public /register flow the owner_app self-signup uses — the
 * new outlet lands as pending_verification, then appears in the pending queue.
 */
export default function OnboardPage() {
  const [form, setForm] = useState({
    restaurant_name: "",
    city: "",
    latitude: "",
    longitude: "",
    username: "",
    password: "",
    upi_id: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegisterOutletResult | null>(null);

  function set(key: keyof typeof form, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function validate(): string | null {
    if (form.restaurant_name.trim().length < 2) return "Enter the restaurant name.";
    if (!VPA_RE.test(form.upi_id.trim())) return "Enter a valid UPI ID (name@bank).";
    if (form.username.trim().length < 3) return "Username must be at least 3 characters.";
    if (form.password.length < 8) return "Password must be at least 8 characters.";
    for (const k of ["latitude", "longitude"] as const) {
      if (form[k].trim() && Number.isNaN(Number(form[k]))) return `Invalid ${k}.`;
    }
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
      const res = await adminApi.registerOutlet({
        restaurant_name: form.restaurant_name.trim(),
        city: form.city.trim() || null,
        latitude: form.latitude.trim() ? Number(form.latitude) : null,
        longitude: form.longitude.trim() ? Number(form.longitude) : null,
        username: form.username.trim(),
        password: form.password,
        upi_id: form.upi_id.trim(),
      });
      setResult(res);
      setForm({
        restaurant_name: "", city: "", latitude: "", longitude: "",
        username: "", password: "", upi_id: "",
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 409 ? "That username is already taken."
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
        <Field label="City (optional)">
          <input className={inputCls} value={form.city}
            onChange={(e) => set("city", e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Latitude (optional)">
            <input className={inputCls} value={form.latitude}
              onChange={(e) => set("latitude", e.target.value)} />
          </Field>
          <Field label="Longitude (optional)">
            <input className={inputCls} value={form.longitude}
              onChange={(e) => set("longitude", e.target.value)} />
          </Field>
        </div>
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
