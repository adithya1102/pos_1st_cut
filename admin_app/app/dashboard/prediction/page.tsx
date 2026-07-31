"use client";

import { useCallback, useEffect, useState } from "react";
import {
  OrderTimeline,
  OutletQuality,
  PredictionOrderRow,
  PredictionOverview,
  adminApi,
} from "@/lib/api";
import { EmptyRow, ErrorBox, Panel, fmtDate, td, th } from "@/components/ui";

/** Shadow-mode observability. Read-only — this page never mutates the engine. */
export default function PredictionPage() {
  const [overview, setOverview] = useState<PredictionOverview | null>(null);
  const [outlets, setOutlets] = useState<OutletQuality[] | null>(null);
  const [orders, setOrders] = useState<PredictionOrderRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      Promise.all([
        adminApi.predictionOverview(),
        adminApi.predictionOutlets(),
        adminApi.predictionOrders(50),
      ]).then(
        ([ov, out, ord]) => {
          setOverview(ov);
          setOutlets(out);
          setOrders(ord);
          setError(null);
        },
        (err: unknown) =>
          setError(err instanceof Error ? err.message : "Failed to load prediction data."),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      {error && <ErrorBox message={error} />}
      <ShadowBanner overview={overview} />
      <OverviewCards overview={overview} />
      <OutletQualityPanel outlets={outlets} />
      <RecentOrdersPanel orders={orders} />
    </>
  );
}

// ------------------------------- FR-A3 -------------------------------------

function ShadowBanner({ overview }: { overview: PredictionOverview | null }) {
  return (
    <div className="rounded border border-indigo-300 bg-indigo-50 px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="inline-block rounded bg-indigo-600 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-white">
          Shadow mode
        </span>
        <span className="text-sm text-indigo-900">
          Predictions are computed and logged but never drive customer promises —
          customers see only a wide, approximate range. This dashboard is read-only.
        </span>
      </div>
      {overview && (
        <p className="mt-2 text-xs text-indigo-700">
          {overview.graduated_outlets === 0
            ? "No outlet has graduated. Kitchen states are system-inferred (single owner app), so kitchen observations stay untrusted by design."
            : `${overview.graduated_outlets} outlet(s) graduated.`}
        </p>
      )}
    </div>
  );
}

// ---------------------------- FR-A4 + metrics ------------------------------

function OverviewCards({ overview }: { overview: PredictionOverview | null }) {
  if (!overview) {
    return <Panel title="Data health"><p className={td}>Loading…</p></Panel>;
  }
  const pct = Math.min(100, overview.progress_pct);
  return (
    <Panel
      title="Data health"
      subtitle={`Global progress toward the ${overview.graduation_threshold}-order training threshold.`}
    >
      <div className="space-y-4 px-4 py-4">
        <div>
          <div className="mb-1 flex items-center justify-between text-sm">
            <span className="text-slate-600">
              {overview.orders_analyzed} / {overview.graduation_threshold} orders analyzed
            </span>
            <span className="font-medium text-slate-800">{pct}%</span>
          </div>
          <div className="h-3 w-full overflow-hidden rounded bg-slate-100">
            <div
              className="h-full rounded bg-emerald-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Metric label="Events" value={overview.total_events} />
          <Metric label="Orders predicted" value={overview.orders_predicted} />
          <Metric
            label="Promise kept"
            value={
              overview.promise_kept_rate === null
                ? "—"
                : `${Math.round(overview.promise_kept_rate * 100)}%`
            }
          />
          <Metric
            label="Avg interval score"
            value={overview.avg_interval_score === null ? "—" : overview.avg_interval_score.toFixed(1)}
            hint="lower is better"
          />
          <Metric label="Trusted travel" value={overview.trusted_travel_observations} />
          <Metric label="Trusted kitchen" value={overview.trusted_kitchen_observations} />
        </div>
      </div>
    </Panel>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded border border-slate-200 px-3 py-2">
      <div className="text-lg font-semibold text-slate-900">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
      {hint && <div className="text-[10px] text-slate-400">{hint}</div>}
    </div>
  );
}

// ------------------------------- FR-A2 -------------------------------------

function OutletQualityPanel({ outlets }: { outlets: OutletQuality[] | null }) {
  return (
    <Panel
      title="Per-outlet quality"
      subtitle="Trust and calibration by outlet. Kitchen trust stays 0 while states are inferred; travel caps at 0.5 on the haversine fallback."
    >
      <table className="w-full">
        <thead className="bg-slate-50">
          <tr>
            <th className={th}>Outlet</th>
            <th className={th}>Orders</th>
            <th className={th}>Promise kept</th>
            <th className={th}>Avg interval</th>
            <th className={th}>Kitchen</th>
            <th className={th}>Travel</th>
            <th className={th}>Customer</th>
            <th className={th}>Tap discipline</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {outlets === null && <EmptyRow colSpan={8}>Loading…</EmptyRow>}
          {outlets?.length === 0 && (
            <EmptyRow colSpan={8}>
              No completed orders yet. Metrics appear once orders finish their pickup cycle.
            </EmptyRow>
          )}
          {outlets?.map((o) => (
            <tr key={o.outlet_id}>
              <td className={`${td} font-medium`}>{o.outlet_name ?? "—"}</td>
              <td className={td}>{o.outcomes}</td>
              <td className={td}>{pctOrDash(o.promise_kept_rate)}</td>
              <td className={td}>{o.avg_interval_score?.toFixed(1) ?? "—"}</td>
              <td className={td}><Trust v={o.avg_kitchen_trust} /></td>
              <td className={td}><Trust v={o.avg_travel_trust} /></td>
              <td className={td}><Trust v={o.avg_customer_trust} /></td>
              <td className={td}>{pctOrDash(o.tap_discipline)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Trust({ v }: { v: number | null }) {
  if (v === null) return <span className="text-slate-400">—</span>;
  const tone =
    v >= 0.75 ? "text-emerald-700" : v >= 0.4 ? "text-amber-700" : "text-slate-500";
  return <span className={`font-medium ${tone}`}>{v.toFixed(2)}</span>;
}

// ------------------------------- FR-A1 -------------------------------------

function RecentOrdersPanel({ orders }: { orders: PredictionOrderRow[] | null }) {
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <Panel
      title="Recent orders"
      subtitle="Every order with an event stream. Expand a row for its full timeline, promise, predictions and outcome."
    >
      <table className="w-full">
        <thead className="bg-slate-50">
          <tr>
            <th className={th}>Order</th>
            <th className={th}>Outlet</th>
            <th className={th}>Status</th>
            <th className={th}>Risk</th>
            <th className={th}>Events</th>
            <th className={th}>Interval</th>
            <th className={th}>Created</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {orders === null && <EmptyRow colSpan={7}>Loading…</EmptyRow>}
          {orders?.length === 0 && (
            <EmptyRow colSpan={7}>No orders with events yet.</EmptyRow>
          )}
          {orders?.map((o) => {
            const open = openId === o.order_id;
            return (
              <FragmentRow
                key={o.order_id}
                order={o}
                open={open}
                onToggle={() => setOpenId(open ? null : o.order_id)}
              />
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}

function FragmentRow({
  order,
  open,
  onToggle,
}: {
  order: PredictionOrderRow;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        className="cursor-pointer hover:bg-slate-50"
        onClick={onToggle}
      >
        <td className={`${td} font-mono text-xs`}>
          <span className="mr-1 inline-block text-slate-400">{open ? "▾" : "▸"}</span>
          {order.order_id.slice(0, 8)}…
        </td>
        <td className={`${td} text-slate-600`}>{order.outlet_name ?? "—"}</td>
        <td className={`${td} text-slate-600`}>{order.status}</td>
        <td className={td}><RiskBadge risk={order.risk_level} /></td>
        <td className={td}>{order.event_count}</td>
        <td className={td}>{order.interval_score?.toFixed(1) ?? "—"}</td>
        <td className={`${td} text-slate-600`}>{fmtDate(order.created_at)}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="bg-slate-50 px-4 py-4">
            <TimelineDetail orderId={order.order_id} />
          </td>
        </tr>
      )}
    </>
  );
}

function RiskBadge({ risk }: { risk: string | null }) {
  if (!risk) return <span className="text-slate-400">—</span>;
  const styles: Record<string, string> = {
    low: "bg-emerald-100 text-emerald-800",
    medium: "bg-amber-100 text-amber-800",
    high: "bg-red-100 text-red-800",
  };
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles[risk] ?? "bg-slate-200 text-slate-700"}`}>
      {risk}
    </span>
  );
}

function TimelineDetail({ orderId }: { orderId: string }) {
  const [tl, setTl] = useState<OrderTimeline | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    adminApi.orderTimeline(orderId).then(
      (data) => {
        if (alive) setTl(data);
      },
      (e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : "Failed to load timeline.");
      },
    );
    return () => {
      alive = false;
    };
  }, [orderId]);

  if (err) return <ErrorBox message={err} />;
  if (!tl) return <p className="text-sm text-slate-500">Loading timeline…</p>;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Event stream */}
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Event stream
        </h4>
        <ol className="space-y-1">
          {tl.events.map((e) => (
            <li key={e.seq} className="flex items-baseline gap-2 text-sm">
              <span className="w-6 shrink-0 text-right font-mono text-xs text-slate-400">
                {e.seq}
              </span>
              <span className="font-medium text-slate-800">{e.event_type}</span>
              <span className="text-xs text-slate-500">
                {e.actor_type}/{e.source}
              </span>
              <span className="ml-auto font-mono text-xs text-slate-400">
                {fmtTime(e.occurred_at)}
              </span>
            </li>
          ))}
        </ol>
      </div>

      {/* Twin + predictions + outcome */}
      <div className="space-y-4">
        {tl.twin && (
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Twin (promise)
            </h4>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <Row k="Shadow range" v={tl.twin.shadow_range_min ? `${tl.twin.shadow_range_min[0]}–${tl.twin.shadow_range_min[1]} min` : "—"} />
              <Row k="Risk" v={tl.twin.risk_level ?? "—"} />
              <Row k="Travel source" v={tl.twin.travel_source ?? "—"} />
              <Row k="Degraded" v={tl.twin.degraded ? "yes" : "no"} />
              <Row k="Promise" v={`${fmtTime(tl.twin.promise_start)} → ${fmtTime(tl.twin.promise_end)}`} />
              <Row k="Ready σ" v={secs(tl.twin.ready_sigma_s)} />
            </dl>
          </div>
        )}

        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Predictions
          </h4>
          {tl.predictions.length === 0 ? (
            <p className="text-sm text-slate-500">None logged.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {tl.predictions.map((p, i) => (
                <li key={i} className="flex items-baseline gap-2">
                  <span className="w-20 shrink-0 font-medium text-slate-700">{p.predictor}</span>
                  <span className="text-xs text-slate-500">
                    {p.mu_seconds !== null ? `μ=${secs(p.mu_seconds)}` : ""}
                    {p.sigma_seconds !== null ? ` σ=${secs(p.sigma_seconds)}` : ""}
                  </span>
                  <span className="ml-auto font-mono text-[10px] text-slate-400">{p.model_version}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {tl.outcome && (
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Outcome
            </h4>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <Row k="Promise kept" v={tl.outcome.promise_kept === null ? "—" : tl.outcome.promise_kept ? "yes" : "no"} />
              <Row k="Interval score" v={tl.outcome.interval_score?.toFixed(1) ?? "—"} />
              <Row k="Kitchen trust" v={tl.outcome.kitchen_trust.toFixed(2)} />
              <Row k="Travel trust" v={tl.outcome.travel_trust.toFixed(2)} />
              <Row k="Customer trust" v={tl.outcome.customer_trust.toFixed(2)} />
              <Row k="Wait feedback" v={tl.outcome.wait_feedback ?? "—"} />
            </dl>
            {tl.outcome.trust_failures.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {tl.outcome.trust_failures.map((f) => (
                  <span key={f} className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-mono text-slate-600">
                    {f}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right font-medium text-slate-800">{v}</dd>
    </>
  );
}

// ------------------------------- helpers -----------------------------------

function pctOrDash(v: number | null): string {
  return v === null ? "—" : `${Math.round(v * 100)}%`;
}

function secs(s: number | null | undefined): string {
  if (s === null || s === undefined) return "—";
  return s >= 60 ? `${(s / 60).toFixed(1)}m` : `${s}s`;
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString();
}
