"use client";

import { useCallback, useEffect, useState } from "react";
import {
  DiscountType,
  Outlet,
  Promotion,
  PromotionCreateBody,
  adminApi,
} from "@/lib/api";
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
 * CareVo Campaigns (migration 016) — promotions CareVo creates and CareVo pays
 * for.
 *
 * Deliberately NOT a generic coupon screen. A restaurant's own offer is a
 * different product with a different funder, created in owner_app, and is not
 * listed or editable here. The `scope` field that distinguishes them is set by
 * the endpoint, so there is nothing on this form to get wrong.
 *
 * Activation is a manual switch. V1 has no scheduler, so a campaign is live
 * exactly when a human says it is.
 */
export default function CampaignsPage() {
  const [rows, setRows] = useState<Promotion[] | null>(null);
  const [outlets, setOutlets] = useState<Outlet[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(
    () =>
      adminApi.promotions().then(
        (data) => {
          setRows(data);
          setError(null);
        },
        (err: unknown) =>
          setError(
            err instanceof Error ? err.message : "Failed to load campaigns.",
          ),
      ),
    [],
  );

  useEffect(() => {
    load();
    // Targeting is optional, so a failure here must not block the screen —
    // the form simply falls back to platform-wide only.
    adminApi.outlets("active").then(setOutlets, () => setOutlets([]));
  }, [load]);

  const toggle = (p: Promotion) => {
    setBusyId(p.id);
    adminApi
      .setPromotionActive(p.id, !p.is_active)
      .then(
        () => load(),
        (err: unknown) =>
          setError(
            err instanceof Error ? err.message : "Could not update the campaign.",
          ),
      )
      .finally(() => setBusyId(null));
  };

  const create = (body: PromotionCreateBody) => {
    setCreating(true);
    setError(null);
    return adminApi
      .createPromotion(body)
      .then(
        () => {
          load();
          return true;
        },
        (err: unknown) => {
          setError(
            err instanceof Error ? err.message : "Could not create the campaign.",
          );
          return false;
        },
      )
      .finally(() => setCreating(false));
  };

  const live = rows?.filter((r) => r.is_active).length ?? 0;

  return (
    <>
      {error && <ErrorBox message={error} />}

      <NewCampaignForm outlets={outlets} busy={creating} onSubmit={create} />

      <Panel
        title="CareVo Campaigns"
        subtitle={
          "Funded by CareVo, not by the restaurant. Platform-wide unless a " +
          "restaurant is named. Restaurants' own offers are created in the owner " +
          "app and are not shown here." +
          (rows ? ` ${live} of ${rows.length} live.` : "")
        }
      >
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>Campaign</th>
              <th className={th}>Code</th>
              <th className={th}>Applies to</th>
              <th className={th}>Creator</th>
              <th className={th}>Redemptions</th>
              <th className={th}>Created</th>
              <th className={th}>Status</th>
              <th className={th}>Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows === null && <EmptyRow colSpan={8}>Loading…</EmptyRow>}
            {rows?.length === 0 && (
              <EmptyRow colSpan={8}>No campaigns yet.</EmptyRow>
            )}
            {rows?.map((p) => (
              <tr key={p.id} className={p.is_active ? undefined : "bg-slate-50/60"}>
                <td className={td}>
                  <div className="font-medium">{p.label}</div>
                  <div className="text-xs text-slate-500">{p.benefit_text}</div>
                </td>
                <td className={td}>
                  {p.code ? (
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                      {p.code}
                    </code>
                  ) : (
                    <span className="text-xs text-slate-400">auto-applied</span>
                  )}
                </td>
                <td className={`${td} text-slate-600`}>
                  {p.outlet_name ?? "All restaurants"}
                </td>
                <td className={`${td} text-slate-600`}>{p.creator_name ?? "—"}</td>
                <td className={td}>
                  {p.redemption_count}
                  {p.max_redemptions_total !== null && (
                    <span className="text-slate-400">
                      {" "}
                      / {p.max_redemptions_total}
                    </span>
                  )}
                </td>
                <td className={`${td} text-slate-600`}>{fmtDate(p.created_at)}</td>
                <td className={td}>
                  <span
                    className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                      p.is_active
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-slate-200 text-slate-600"
                    }`}
                  >
                    {p.is_active ? "live" : "paused"}
                  </span>
                </td>
                <td className={td}>
                  <Button
                    variant={p.is_active ? "danger" : "primary"}
                    disabled={busyId === p.id}
                    onClick={() => toggle(p)}
                  >
                    {p.is_active ? "Deactivate" : "Activate"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}

const input =
  "w-full rounded border border-slate-300 px-2 py-1.5 text-sm " +
  "focus:border-slate-500 focus:outline-none";
const labelCls = "block text-xs font-medium text-slate-600";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className={labelCls}>{label}</span>
      {children}
      {hint && <span className="block text-xs text-slate-400">{hint}</span>}
    </label>
  );
}

function NewCampaignForm({
  outlets,
  busy,
  onSubmit,
}: {
  outlets: Outlet[];
  busy: boolean;
  onSubmit: (body: PromotionCreateBody) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [code, setCode] = useState("");
  const [outletId, setOutletId] = useState("");
  const [discountType, setDiscountType] = useState<DiscountType>("PERCENT");
  const [discountValue, setDiscountValue] = useState("");
  const [maxDiscount, setMaxDiscount] = useState("");
  const [minOrder, setMinOrder] = useState("");
  const [creator, setCreator] = useState("");
  const [maxTotal, setMaxTotal] = useState("");
  const [perCustomer, setPerCustomer] = useState("1");
  const [activateNow, setActivateNow] = useState(false);

  function reset() {
    setLabel("");
    setCode("");
    setOutletId("");
    setDiscountType("PERCENT");
    setDiscountValue("");
    setMaxDiscount("");
    setMinOrder("");
    setCreator("");
    setMaxTotal("");
    setPerCustomer("1");
    setActivateNow(false);
  }

  /** "" -> null, so an untouched optional field clears rather than sending 0. */
  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const ok = await onSubmit({
      label: label.trim(),
      code: code.trim() === "" ? null : code.trim().toUpperCase(),
      outlet_id: outletId === "" ? null : outletId,
      discount_type: discountType,
      discount_value: Number(discountValue),
      max_discount_amount: num(maxDiscount),
      min_order_value: num(minOrder),
      creator_name: creator.trim() === "" ? null : creator.trim(),
      max_redemptions_total: num(maxTotal),
      max_redemptions_per_customer: Number(perCustomer) || 1,
      is_active: activateNow,
    });
    if (ok) {
      reset();
      setOpen(false);
    }
  }

  if (!open) {
    return (
      <div>
        <Button variant="primary" onClick={() => setOpen(true)}>
          New campaign
        </Button>
      </div>
    );
  }

  return (
    <Panel
      title="New CareVo Campaign"
      subtitle="CareVo funds this. Leave the restaurant blank to run it everywhere."
    >
      <form onSubmit={submit} className="space-y-4 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" hint="Shown to customers.">
            <input
              className={input}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Monsoon ₹75 off"
              required
              maxLength={120}
            />
          </Field>
          <Field
            label="Code (optional)"
            hint="Leave blank to auto-apply with no code to type."
          >
            <input
              className={input}
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="MONSOON75"
              maxLength={24}
            />
          </Field>

          <Field label="Discount type">
            <select
              className={input}
              value={discountType}
              onChange={(e) => setDiscountType(e.target.value as DiscountType)}
            >
              <option value="PERCENT">Percentage off</option>
              <option value="FLAT">Flat ₹ off</option>
            </select>
          </Field>
          <Field label={discountType === "PERCENT" ? "Percent off" : "Rupees off"}>
            <input
              className={input}
              type="number"
              min="0.01"
              max={discountType === "PERCENT" ? "100" : undefined}
              step="0.01"
              value={discountValue}
              onChange={(e) => setDiscountValue(e.target.value)}
              required
            />
          </Field>

          <Field
            label="Max discount ₹ (optional)"
            hint={
              discountType === "PERCENT"
                ? "Caps a percentage on large orders. Optional here because CareVo funds it — it is REQUIRED for a restaurant's own percentage offer."
                : "Not used for flat discounts."
            }
          >
            <input
              className={input}
              type="number"
              min="0.01"
              step="0.01"
              value={maxDiscount}
              onChange={(e) => setMaxDiscount(e.target.value)}
              disabled={discountType !== "PERCENT"}
            />
          </Field>
          <Field label="Minimum order ₹ (optional)">
            <input
              className={input}
              type="number"
              min="0"
              step="0.01"
              value={minOrder}
              onChange={(e) => setMinOrder(e.target.value)}
            />
          </Field>

          <Field
            label="Restaurant (optional)"
            hint="Blank = every restaurant. CareVo still funds it either way."
          >
            <select
              className={input}
              value={outletId}
              onChange={(e) => setOutletId(e.target.value)}
            >
              <option value="">All restaurants</option>
              {outlets.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.location_name}
                  {o.city ? ` — ${o.city}` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Creator / partner (optional)" hint="Attribution only.">
            <input
              className={input}
              value={creator}
              onChange={(e) => setCreator(e.target.value)}
              maxLength={80}
            />
          </Field>

          <Field label="Total redemptions (optional)" hint="Blank = unlimited.">
            <input
              className={input}
              type="number"
              min="1"
              step="1"
              value={maxTotal}
              onChange={(e) => setMaxTotal(e.target.value)}
            />
          </Field>
          <Field label="Per customer">
            <input
              className={input}
              type="number"
              min="1"
              step="1"
              value={perCustomer}
              onChange={(e) => setPerCustomer(e.target.value)}
            />
          </Field>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={activateNow}
            onChange={(e) => setActivateNow(e.target.checked)}
          />
          {/* Off by default on the server too — nothing goes live by accident. */}
          Activate immediately
        </label>

        <div className="flex gap-2">
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Creating…" : "Create campaign"}
          </Button>
          <Button type="button" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </form>
    </Panel>
  );
}
