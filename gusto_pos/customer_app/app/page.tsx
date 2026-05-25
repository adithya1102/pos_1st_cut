'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { API_BASE } from '@/lib/api';

const OUTLET_ID = process.env.NEXT_PUBLIC_OUTLET_ID || '0b8a8349-6144-41a8-b028-b9089bd8eaea';

type Session = {
  token: string;
  table_id: string;
  zone: string;
  created_at: string;
  expires_at: string;
};

export default function DevLandingPage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newTableId, setNewTableId] = useState('');
  const [newZone, setNewZone] = useState<'normal' | 'ac'>('normal');
  const [error, setError] = useState<string | null>(null);

  const fetchSessions = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/tables/active?outlet_id=${OUTLET_ID}`);
      if (!res.ok) throw new Error(`Server returned HTTP ${res.status}`);
      const data = await res.json();
      setSessions(Array.isArray(data) ? data : []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch sessions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const openSession = async () => {
    if (!newTableId.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/tables/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          outlet_id: OUTLET_ID,
          table_id: newTableId.trim(),
          zone: newZone,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      setNewTableId('');
      await fetchSessions();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to open session');
    } finally {
      setCreating(false);
    }
  };

  const enterManualToken = () => {
    const t = window.prompt('Enter session token (e.g. YRW5AM):');
    if (t?.trim()) router.push(`/menu?t=${t.trim().toUpperCase()}`);
  };

  return (
    <div className="min-h-screen bg-[#0f172a] text-[#f8fafc] px-4 py-8">
      <div className="mx-auto max-w-xl">

        {/* Header */}
        <div className="mb-8 flex items-center gap-3">
          <span className="rounded bg-[#f97316] px-2 py-0.5 text-xs font-bold uppercase tracking-widest text-white">
            Dev
          </span>
          <h1 className="text-2xl font-bold tracking-tight">QR Simulator</h1>
        </div>

        {/* Active sessions */}
        <section className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500">
              Active Sessions
            </h2>
            <button
              onClick={fetchSessions}
              className="text-xs text-slate-600 hover:text-slate-300 transition-colors"
            >
              ↻ Refresh
            </button>
          </div>

          {loading && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-[#f97316] border-t-transparent" />
              Loading sessions…
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-800/60 bg-red-950/40 p-3 text-sm text-red-400">
              {error}
            </div>
          )}

          {!loading && !error && sessions.length === 0 && (
            <p className="text-sm text-slate-600">
              No active sessions. Open a table below to generate a token.
            </p>
          )}

          {!loading && sessions.length > 0 && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {sessions.map((s) => (
                <button
                  key={s.token}
                  onClick={() => router.push(`/menu?t=${s.token}`)}
                  className="group rounded-xl border border-transparent bg-[#1e293b] p-4 text-left transition-colors hover:border-[#f97316]/30 hover:bg-[#f97316]/10"
                >
                  <div className="text-lg font-bold text-[#f97316] group-hover:text-[#fb923c]">
                    {s.table_id}
                  </div>
                  <div
                    className={`mt-1 text-xs font-semibold ${
                      s.zone === 'ac' ? 'text-blue-400' : 'text-emerald-400'
                    }`}
                  >
                    {s.zone === 'ac' ? 'AC Zone' : 'Normal Zone'}
                  </div>
                  <div className="mt-2 font-mono text-xs text-slate-600">
                    {s.token}
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Open new session */}
        <section className="rounded-xl bg-[#1e293b] p-5">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-500">
            Open New Table
          </h2>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Table ID (e.g. N-1)"
              value={newTableId}
              onChange={(e) => setNewTableId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && openSession()}
              className="flex-1 rounded-lg bg-[#0f172a] px-3 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:ring-1 focus:ring-[#f97316]/50"
            />
            <select
              value={newZone}
              onChange={(e) => setNewZone(e.target.value as 'normal' | 'ac')}
              className="rounded-lg bg-[#0f172a] px-3 py-2 text-sm text-slate-200 outline-none focus:ring-1 focus:ring-[#f97316]/50"
            >
              <option value="normal">Normal</option>
              <option value="ac">AC</option>
            </select>
            <button
              onClick={openSession}
              disabled={creating || !newTableId.trim()}
              className="rounded-lg bg-[#f97316] px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#ea6f10] disabled:opacity-40"
            >
              {creating ? '…' : 'Open'}
            </button>
          </div>
          <p className="mt-3 font-mono text-xs text-slate-700">
            outlet: {OUTLET_ID}
          </p>
        </section>

        {/* Manual token fallback */}
        <p className="mt-6 text-xs text-slate-700">
          Have a token already?{' '}
          <button
            onClick={enterManualToken}
            className="text-[#f97316] hover:underline"
          >
            Enter it manually
          </button>
        </p>

      </div>
    </div>
  );
}
