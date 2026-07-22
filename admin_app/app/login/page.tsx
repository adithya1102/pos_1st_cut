"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, adminApi, clearToken, login, setToken } from "@/lib/api";
import { Button, ErrorBox } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const token = await login(username, password);
      setToken(token);
      // Credentials can be valid staff credentials without being a super admin.
      // Verify the role now so the failure surfaces here, not as a blank dashboard.
      await adminApi.me();
      router.replace("/dashboard");
    } catch (err) {
      clearToken();
      if (err instanceof ApiError && err.status === 403) {
        setError("That account is valid staff, but does not have the SUPER_ADMIN role.");
      } else if (err instanceof ApiError && err.status === 401) {
        setError("Incorrect username or password.");
      } else {
        setError(err instanceof Error ? err.message : "Login failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded border border-slate-200 bg-white p-6"
      >
        <div>
          <h1 className="text-lg font-semibold">CareVo Admin</h1>
          <p className="mt-1 text-sm text-slate-500">
            Sign in with your staff account.
          </p>
        </div>

        {error && <ErrorBox message={error} />}

        <label className="block text-sm">
          <span className="font-medium">Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          />
        </label>

        <label className="block text-sm">
          <span className="font-medium">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          />
        </label>

        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </main>
  );
}
