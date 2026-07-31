"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AdminMe, adminApi, clearToken, getToken } from "@/lib/api";
import { Button } from "@/components/ui";

const NAV = [
  { href: "/dashboard", label: "Pending queue" },
  { href: "/dashboard/outlets", label: "All outlets" },
  { href: "/dashboard/onboard", label: "Onboard restaurant" },
  { href: "/dashboard/locked-orders", label: "Locked orders" },
  { href: "/dashboard/prediction", label: "Prediction engine" },
  { href: "/dashboard/audit", label: "Audit log" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<AdminMe | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    // Single gate for every dashboard page: a stale or non-admin token bounces
    // to /login rather than rendering an empty shell.
    adminApi
      .me()
      .then(setMe)
      .catch(() => {
        clearToken();
        router.replace("/login");
      });
  }, [router]);

  function signOut() {
    clearToken();
    router.replace("/login");
  }

  if (!me) {
    return (
      <main className="p-8 text-sm text-slate-500">Checking credentials…</main>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <span className="font-semibold">CareVo Admin</span>
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <span>{me.username}</span>
            <Button onClick={signOut}>Sign out</Button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-6xl gap-1 px-6">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`border-b-2 px-3 py-2 text-sm ${
                  active
                    ? "border-slate-900 font-medium text-slate-900"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 p-6">{children}</main>
    </div>
  );
}
