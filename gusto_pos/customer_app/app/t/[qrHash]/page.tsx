'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';

type PageState = 'loading' | 'error';

export default function QRHashPage() {
  const router = useRouter();
  const params = useParams<{ qrHash: string }>();
  const qrHash = params.qrHash;

  const [state, setState] = useState<PageState>('loading');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    if (!qrHash) return;
    validateAndRedirect();
  }, [qrHash]);

  async function validateAndRedirect() {
    setState('loading');
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://pos-1st-cut.onrender.com';
      const res = await fetch(`${API_BASE}/api/v1/tables/validate/${qrHash}`);

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setState('error');
        setErrorMessage(data?.detail ?? `Unexpected error (${res.status}).`);
        return;
      }

      const data = await res.json();
      if (!data.is_valid) {
        setState('error');
        setErrorMessage(data?.message ?? 'Invalid or expired QR code.');
        return;
      }

      router.replace(`/menu/${qrHash}`);
    } catch {
      setState('error');
      setErrorMessage('Unable to reach the server. Please check your connection.');
    }
  }

  if (state === 'loading') {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="mb-4 inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-blue-600 border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]"></div>
          <p className="text-lg font-semibold text-gray-700">Opening your menu...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full items-center justify-center bg-gray-50 p-6">
      <div className="text-center bg-white p-8 rounded-xl shadow-md border-t-4 border-yellow-500">
        <div className="text-4xl mb-4">⚠️</div>
        <h2 className="text-xl font-bold text-gray-800 mb-2">QR Code Error</h2>
        <p className="text-gray-600 mb-4">{errorMessage || 'An unexpected error occurred.'}</p>
        <button
          onClick={validateAndRedirect}
          className="rounded-lg px-6 py-2 text-white font-semibold"
          style={{ backgroundColor: '#1B4332' }}
        >
          Try Again
        </button>
      </div>
    </div>
  );
}
