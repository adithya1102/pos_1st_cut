'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';

type PageState = 'verifying' | 'denied' | 'too_far' | 'error';

export default function QRHashPage() {
  const router = useRouter();
  const params = useParams<{ qrHash: string }>();
  const qrHash = params.qrHash;

  const [state, setState] = useState<PageState>('verifying');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    if (!qrHash) return;

    if (!navigator.geolocation) {
      setState('error');
      setErrorMessage('Geolocation is not supported by your browser.');
      return;
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        try {
          const API_BASE = 'http://192.168.1.7:8000';
          const res = await fetch(
            `${API_BASE}/api/v1/tables/${qrHash}/session`,
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ latitude, longitude }),
            }
          );

          if (res.status === 403) {
            setState('too_far');
            return;
          }

          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            setState('error');
            setErrorMessage(data?.detail ?? `Unexpected error (${res.status}).`);
            return;
          }

          const data = await res.json();
          const token: string = data.token ?? data.session_token ?? data.qr_token;
          router.replace(`/menu/${token}`);
        } catch {
          setState('error');
          setErrorMessage('Unable to reach the server. Please check your connection.');
        }
      },
      () => {
        setState('denied');
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }, [qrHash, router]);

  if (state === 'verifying') {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="mb-4 inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-blue-600 border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]"></div>
          <p className="text-lg font-semibold text-gray-700">Verifying location...</p>
        </div>
      </div>
    );
  }

  if (state === 'denied') {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50 p-6">
        <div className="text-center bg-white p-8 rounded-xl shadow-md">
          <div className="text-4xl mb-4">📍</div>
          <h2 className="text-xl font-bold text-gray-800 mb-2">Location Required</h2>
          <p className="text-gray-600">Location access is required to view the live menu. Please enable it in your browser settings and refresh.</p>
        </div>
      </div>
    );
  }

  if (state === 'too_far') {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50 p-6">
        <div className="text-center bg-white p-8 rounded-xl shadow-md border-t-4 border-red-500">
          <div className="text-4xl mb-4">🗺️</div>
          <h2 className="text-xl font-bold text-gray-800 mb-2">Too Far Away</h2>
          <p className="text-gray-600">You appear to be too far from the restaurant to open a live tab.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full items-center justify-center bg-gray-50 p-6">
      <div className="text-center bg-white p-8 rounded-xl shadow-md border-t-4 border-yellow-500">
        <div className="text-4xl mb-4">⚠️</div>
        <h2 className="text-xl font-bold text-gray-800 mb-2">Something went wrong</h2>
        <p className="text-gray-600">{errorMessage || 'An unexpected error occurred.'}</p>
      </div>
    </div>
  );
}
