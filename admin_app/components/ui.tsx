"use client";

/** Minimal shared primitives. Internal tool — no design system, just consistency. */

export function Button({
  children,
  variant = "default",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "danger";
}) {
  const styles = {
    default: "bg-white border-slate-300 text-slate-700 hover:bg-slate-50",
    primary: "bg-emerald-600 border-emerald-600 text-white hover:bg-emerald-700",
    danger: "bg-red-600 border-red-600 text-white hover:bg-red-700",
  }[variant];

  return (
    <button
      {...props}
      className={`rounded border px-3 py-1.5 text-sm font-medium transition
        disabled:cursor-not-allowed disabled:opacity-50 ${styles}`}
    >
      {children}
    </button>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: "bg-emerald-100 text-emerald-800",
    pending_verification: "bg-amber-100 text-amber-800",
    rejected: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
        styles[status] ?? "bg-slate-200 text-slate-700"
      }`}
    >
      {status}
    </span>
  );
}

export function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded border border-slate-200 bg-white">
      <header className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-base font-semibold">{title}</h2>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </header>
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: React.ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-8 text-center text-sm text-slate-500">
        {children}
      </td>
    </tr>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
      {message}
    </div>
  );
}

export const th = "px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500";
export const td = "px-4 py-3 text-sm";

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}
