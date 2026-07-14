'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';

const API = `${process.env.NEXT_PUBLIC_API_URL || 'https://pos-1st-cut.onrender.com'}/api/v1`;

type Step = 'loading' | 'details' | 'otp' | 'error';

export default function CustomerLoginPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const [step, setStep] = useState<Step>('loading');
  const [tableId, setTableId] = useState('');
  const [outletId, setOutletId] = useState('');
  const [zone, setZone] = useState('normal');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [devOtp, setDevOtp] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!slug) return;
    fetch(`${API}/tables/validate/${encodeURIComponent(slug)}`)
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok || !data.is_valid) throw new Error(data.message || 'Invalid or expired QR code.');
        setTableId(data.table_id);
        setOutletId(data.outlet_id);
        setZone(data.zone || 'normal');
        localStorage.setItem('table_zone', data.zone || 'normal');
        setStep('details');
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Could not validate this table.');
        setStep('error');
      });
  }, [slug]);

  async function sendOtp() {
    if (!name.trim() || !/^\d{10}$/.test(phone)) {
      setError('Enter your name and a valid 10-digit phone number.');
      return;
    }
    setError('');
    try {
      const res = await fetch(`${API}/sessions/send-otp`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: `+91${phone}`, table_id: tableId, outlet_id: outletId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not send OTP.');
      setDevOtp(data.dev_otp || '');
      setStep('otp');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not send OTP.');
    }
  }

  async function verifyOtp() {
    if (!/^\d{6}$/.test(otp)) { setError('Enter the 6-digit OTP.'); return; }
    setError('');
    try {
      const res = await fetch(`${API}/sessions/verify-otp`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: `+91${phone}`, otp, table_id: tableId, outlet_id: outletId, customer_name: name.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Invalid OTP.');
      localStorage.setItem('customer_session_id', data.session_id || '');
      localStorage.setItem('customer_phone', `+91${phone}`);
      localStorage.setItem('customer_name', name.trim());
      router.replace(`/menu?t=${encodeURIComponent(slug)}&zone=${encodeURIComponent(zone)}&outlet_id=${encodeURIComponent(outletId)}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not verify OTP.');
    }
  }

  const box = { minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0f172a', padding: 20 };
  const card = { width: '100%', maxWidth: 390, background: '#fff', borderRadius: 18, padding: 28 };
  if (step === 'loading') return <div style={box}><div style={card}><p>Validating table...</p></div></div>;
  if (step === 'error') return <div style={box}><div style={card}><h2>QR code unavailable</h2><p>{error}</p></div></div>;
  return <div style={box}><div style={card}>
    <h1 style={{ color: '#1B4332', marginTop: 0 }}>Rudrarthi</h1>
    <p>Table {tableId}. Sign in to start ordering.</p>
    {step === 'details' ? <>
      <input value={name} onChange={e => setName(e.target.value)} placeholder="Your name" style={{ width: '100%', padding: 12, marginBottom: 10, boxSizing: 'border-box' }} />
      <input value={phone} onChange={e => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))} placeholder="10-digit phone number" inputMode="numeric" style={{ width: '100%', padding: 12, boxSizing: 'border-box' }} />
      <button onClick={sendOtp} style={{ width: '100%', padding: 13, marginTop: 16, background: '#1B4332', color: '#fff', border: 0, borderRadius: 8 }}>Send OTP</button>
    </> : <>
      <p>Enter the OTP sent to +91 {phone}.</p>
      {devOtp && <p style={{ color: '#856404' }}>Development OTP: {devOtp}</p>}
      <input value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit OTP" inputMode="numeric" style={{ width: '100%', padding: 12, boxSizing: 'border-box' }} />
      <button onClick={verifyOtp} style={{ width: '100%', padding: 13, marginTop: 16, background: '#1B4332', color: '#fff', border: 0, borderRadius: 8 }}>Verify and open menu</button>
    </>}
    {error && <p style={{ color: '#b91c1c', marginBottom: 0 }}>{error}</p>}
  </div></div>;
}
