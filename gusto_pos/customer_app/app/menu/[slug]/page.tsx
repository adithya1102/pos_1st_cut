'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';

const API = process.env.NEXT_PUBLIC_API_URL ? `${process.env.NEXT_PUBLIC_API_URL}/api/v1` : 'http://127.0.0.1:8000/api/v1';
const OUTLET_ID = '0b8a8349-6144-41a8-b028-b9089bd8eaea';

type Step = 'loading' | 'error' | 'login' | 'otp' | 'waiting';

// ── Shared UI components (defined outside to avoid re-creation on each render) ──

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #1B4332, #2d6a4f)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 16,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      <div style={{
        background: '#fff',
        borderRadius: 20,
        maxWidth: 380,
        width: '100%',
        padding: 32,
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      }}>
        {children}
      </div>
    </div>
  );
}

function Header() {
  return (
    <div style={{ textAlign: 'center', marginBottom: 24 }}>
      <div style={{ fontSize: 48, marginBottom: 8 }}>🍽️</div>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: '#1B4332', margin: 0 }}>
        Rudrarthi
      </h1>
    </div>
  );
}

function PrimaryButton({ onClick, disabled, children }: {
  onClick: () => void; disabled?: boolean; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        width: '100%',
        padding: '14px 0',
        background: disabled ? '#9ca3af' : '#1B4332',
        color: '#fff',
        border: 'none',
        borderRadius: 10,
        fontSize: 16,
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        marginTop: 16,
        transition: 'background 0.2s',
      }}
    >
      {children}
    </button>
  );
}

export default function QREntryPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;

  // State
  const [step, setStep] = useState<Step>('loading');
  const [errorMsg, setErrorMsg] = useState('');
  const [tableId, setTableId] = useState('');
  const [outletId, setOutletId] = useState('');

  // Login fields
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [phoneError, setPhoneError] = useState('');

  // OTP fields
  const [otp, setOtp] = useState('');
  const [devOtp, setDevOtp] = useState('');
  const [otpError, setOtpError] = useState('');
  const [fullPhone, setFullPhone] = useState('');

  // Session
  const [sessionId, setSessionId] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [busy, setBusy] = useState(false);

  // Zone state
  const [zone, setZone] = useState('normal');

  // Redirect helper — must include token so menu page can validate
  const goToMenu = useCallback((oid: string, tid: string, z: string = 'normal') => {
    router.push(`/menu?outlet_id=${oid}&table_id=${tid}&token=${slug}&zone=${z}`);
  }, [router, slug]);

  // ── STEP A — Validate slug/token ──
  useEffect(() => {
    if (!slug) return;

    (async () => {
      try {
        console.log("FETCHING MENU FOR TOKEN:", slug);
        const res = await fetch(`${API}/tables/validate/${slug}`);

        if (!res.ok) {
          throw new Error(`Server returned ${res.status}: ${res.statusText}`);
        }

        let data: Record<string, unknown>;
        try {
          data = await res.json();
        } catch (parseErr) {
          throw new Error(`Failed to parse server response: ${parseErr instanceof Error ? parseErr.message : String(parseErr)}`);
        }

        console.log("MENU DATA:", data);

        if (!data.is_valid) {
          // Check if it's a closed-table vs truly invalid
          const msg = ((data.message as string) || '').toLowerCase();
          if (msg.includes('expired') || msg.includes('closed') || msg.includes('reopen') || msg.includes('not active') || msg.includes('open the table')) {
            setErrorMsg('Table not active. Ask your waiter to open the table.');
          } else {
            setErrorMsg(`Invalid QR code. Please ask your waiter. (${data.message || 'unknown reason'})`);
          }
          setStep('error');
          return;
        }

        // Valid token
        setTableId((data.table_id as string) || '');
        setOutletId((data.outlet_id as string) || '');
        const tableZone = (data.zone as string) || 'normal';
        setZone(tableZone);
        localStorage.setItem('table_zone', tableZone);

        // ── STEP B — Check existing session ──
        const key = `session_${data.table_id}`;
        const saved = localStorage.getItem(key);
        if (saved) {
          try {
            const parsed = JSON.parse(saved);
            const statusRes = await fetch(`${API}/sessions/status/${parsed.session_id}`);
            const status = await statusRes.json();
            if (status.confirmed && !status.expired) {
              goToMenu((data.outlet_id as string) || '', (data.table_id as string) || '', tableZone);
              return;
            }
          } catch { /* ignore stale session */ }
          localStorage.removeItem(key);
        }

        setStep('login');
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        console.error("Token validation failed:", msg);
        setErrorMsg(`Could not connect to server: ${msg}`);
        setStep('error');
      }
    })();
  }, [slug, goToMenu]);

  // ── STEP C — Send OTP ──
  const handleSendOtp = async () => {
    setPhoneError('');
    if (phone.length !== 10 || !/^\d{10}$/.test(phone)) {
      setPhoneError('Enter a valid 10-digit phone number');
      return;
    }
    const fp = `+91${phone}`;
    setFullPhone(fp);
    setBusy(true);
    try {
      const res = await fetch(`${API}/sessions/send-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: fp }),
      });
      const data = await res.json();
      if (data.dev_otp) setDevOtp(data.dev_otp);
      setStep('otp');
    } catch {
      setPhoneError('Failed to send OTP. Try again.');
    } finally {
      setBusy(false);
    }
  };

  // ── STEP D — Verify OTP ──
  const handleVerifyOtp = async () => {
    setOtpError('');
    if (otp.length !== 6) {
      setOtpError('Enter 6-digit OTP');
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${API}/sessions/verify-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phone: fullPhone,
          otp,
          table_id: tableId,
          outlet_id: outletId || OUTLET_ID,
          customer_name: name || fullPhone,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setOtpError(data.detail || 'Invalid OTP');
        setBusy(false);
        return;
      }
      setSessionId(data.session_id);

      // Save to localStorage
      localStorage.setItem(`session_${tableId}`, JSON.stringify({
        session_id: data.session_id,
        phone: fullPhone,
      }));

      if (data.confirmed) {
        goToMenu(outletId || OUTLET_ID, tableId, zone);
      } else {
        setStep('waiting');
      }
    } catch {
      setOtpError('Network error. Try again.');
    } finally {
      setBusy(false);
    }
  };

  // ── STEP E — Poll for waiter confirmation ──
  useEffect(() => {
    if (step !== 'waiting' || !sessionId) return;

    const poll = async () => {
      try {
        const res = await fetch(`${API}/sessions/status/${sessionId}`);
        const data = await res.json();
        if (data.confirmed) {
          if (pollRef.current) clearInterval(pollRef.current);
          goToMenu(outletId || OUTLET_ID, tableId, zone);
        }
      } catch { /* retry next tick */ }
    };

    poll(); // check immediately
    pollRef.current = setInterval(poll, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [step, sessionId, outletId, tableId, goToMenu]);

  // ──────────── RENDER ────────────

  // ── Loading ──
  if (step === 'loading') {
    return (
      <Wrapper>
        <Header />
        <div style={{ textAlign: 'center' }}>
          <div style={{
            width: 40, height: 40, border: '4px solid #e5e7eb',
            borderTopColor: '#1B4332', borderRadius: '50%',
            animation: 'spin 1s linear infinite',
            margin: '0 auto 16px',
          }} />
          <p style={{ color: '#6b7280', fontSize: 14 }}>Validating your table...</p>
          <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
        </div>
      </Wrapper>
    );
  }

  // ── Error ──
  if (step === 'error') {
    return (
      <Wrapper>
        <Header />
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>🚫</div>
          <p style={{ color: '#dc2626', fontWeight: 600, fontSize: 16, margin: '0 0 8px' }}>
            {errorMsg}
          </p>
          <p style={{ color: '#9ca3af', fontSize: 13 }}>
            Please ask your server for assistance.
          </p>
        </div>
      </Wrapper>
    );
  }

  // ── Login (Phone) ──
  if (step === 'login') {
    return (
      <Wrapper>
        <Header />
        <p style={{ textAlign: 'center', color: '#6b7280', fontSize: 14, marginBottom: 20 }}>
          Table <strong style={{ color: '#1B4332' }}>{tableId}</strong> — Enter your phone to continue
        </p>

        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#374151', marginBottom: 4, fontWeight: 500 }}>
            Name <span style={{ color: '#9ca3af' }}>(optional)</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Your name"
            style={{
              width: '100%', padding: '12px 14px', border: '2px solid #e5e7eb',
              borderRadius: 10, fontSize: 15, outline: 'none', boxSizing: 'border-box',
              color: '#000', transition: 'border-color 0.2s',
            }}
            onFocus={e => e.target.style.borderColor = '#1B4332'}
            onBlur={e => e.target.style.borderColor = '#e5e7eb'}
          />
        </div>

        <div style={{ marginBottom: 6 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#374151', marginBottom: 4, fontWeight: 500 }}>
            Phone Number
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{
              padding: '12px 14px', background: '#f3f4f6', borderRadius: 10,
              fontSize: 15, color: '#374151', fontWeight: 600, whiteSpace: 'nowrap',
            }}>
              +91
            </div>
            <input
              type="tel"
              value={phone}
              onChange={e => {
                const v = e.target.value.replace(/\D/g, '').slice(0, 10);
                setPhone(v);
                setPhoneError('');
              }}
              placeholder="9876543210"
              maxLength={10}
              style={{
                flex: 1, padding: '12px 14px', border: '2px solid #e5e7eb',
                borderRadius: 10, fontSize: 15, outline: 'none', boxSizing: 'border-box',
                color: '#000', transition: 'border-color 0.2s',
              }}
              onFocus={e => e.target.style.borderColor = '#1B4332'}
              onBlur={e => e.target.style.borderColor = '#e5e7eb'}
            />
          </div>
          {phoneError && (
            <p style={{ color: '#dc2626', fontSize: 12, marginTop: 4 }}>{phoneError}</p>
          )}
        </div>

        <PrimaryButton onClick={handleSendOtp} disabled={busy}>
          {busy ? 'Sending...' : 'Send OTP'}
        </PrimaryButton>
      </Wrapper>
    );
  }

  // ── OTP Verification ──
  if (step === 'otp') {
    return (
      <Wrapper>
        <Header />
        <p style={{ textAlign: 'center', color: '#6b7280', fontSize: 14, marginBottom: 20 }}>
          Enter the 6-digit OTP sent to <strong>{fullPhone}</strong>
        </p>

        {devOtp && (
          <div style={{
            background: '#dcfce7', border: '2px solid #22c55e', borderRadius: 10,
            padding: '12px 16px', textAlign: 'center', marginBottom: 16,
          }}>
            <p style={{ color: '#15803d', fontSize: 12, fontWeight: 600, margin: '0 0 4px' }}>
              DEV MODE OTP:
            </p>
            <p style={{ color: '#15803d', fontSize: 24, fontWeight: 700, letterSpacing: 6, margin: 0 }}>
              {devOtp}
            </p>
          </div>
        )}

        <input
          type="text"
          value={otp}
          onChange={e => {
            const v = e.target.value.replace(/\D/g, '').slice(0, 6);
            setOtp(v);
            setOtpError('');
          }}
          placeholder="• • • • • •"
          maxLength={6}
          style={{
            width: '100%', padding: '16px', border: '2px solid #e5e7eb',
            borderRadius: 10, fontSize: 28, fontWeight: 700, textAlign: 'center',
            letterSpacing: 12, outline: 'none', boxSizing: 'border-box',
            color: '#212529', backgroundColor: '#FFFFFF',
            transition: 'border-color 0.2s',
          }}
          onFocus={e => e.target.style.borderColor = '#1B4332'}
          onBlur={e => e.target.style.borderColor = '#e5e7eb'}
        />
        {otpError && (
          <p style={{ color: '#dc2626', fontSize: 12, marginTop: 4, textAlign: 'center' }}>{otpError}</p>
        )}

        <PrimaryButton onClick={handleVerifyOtp} disabled={busy}>
          {busy ? 'Verifying...' : 'Verify'}
        </PrimaryButton>

        <button
          onClick={() => { setStep('login'); setOtp(''); setDevOtp(''); setOtpError(''); }}
          style={{
            width: '100%', padding: '10px 0', background: 'transparent',
            color: '#6b7280', border: 'none', fontSize: 13, cursor: 'pointer',
            marginTop: 8,
          }}
        >
          ← Change phone number
        </button>
      </Wrapper>
    );
  }

  // ── Waiting for Waiter ──
  if (step === 'waiting') {
    return (
      <Wrapper>
        <Header />
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>👋</div>
          <h2 style={{ color: '#1B4332', fontSize: 20, fontWeight: 700, margin: '0 0 8px' }}>
            Waiter Notified!
          </h2>
          <p style={{ color: '#6b7280', fontSize: 14, margin: '0 0 20px' }}>
            Your request has been sent to the waiter. They will confirm your table shortly — please stay seated.
          </p>
          <div style={{
            width: 40, height: 40, border: '4px solid #e5e7eb',
            borderTopColor: '#1B4332', borderRadius: '50%',
            animation: 'spin 1s linear infinite',
            margin: '0 auto 16px',
          }} />
          <p style={{ color: '#9ca3af', fontSize: 12 }}>
            This page will redirect automatically once confirmed.
          </p>
          <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
        </div>
      </Wrapper>
    );
  }

  // Fallback (should never reach here)
  return null;
}