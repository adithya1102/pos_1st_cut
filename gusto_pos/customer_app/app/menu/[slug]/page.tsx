'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';

const API = 'http://192.168.1.7:8000/api/v1';

type Step = 'loading' | 'error' | 'login';

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

  const [step, setStep] = useState<Step>('loading');
  const [errorMsg, setErrorMsg] = useState('');
  const [tableId, setTableId] = useState('');
  const [outletId, setOutletId] = useState('');
  const [zone, setZone] = useState('normal');
  const [phone, setPhone] = useState('');
  const [phoneError, setPhoneError] = useState('');

  // Pass only the static token — menu page resolves outlet/zone from backend
  const goToMenu = useCallback((_oid: string, _tid: string, _z: string = 'normal') => {
    router.push(`/menu?t=${slug}`);
  }, [router, slug]);

  useEffect(() => {
    if (!slug) return;

    (async () => {
      try {
        const res = await fetch(`${API}/tables/validate/${slug}`);
        const data = await res.json();

        if (!data.is_valid) {
          const msg = (data.message || '').toLowerCase();
          setErrorMsg(
            msg.includes('expired') || msg.includes('closed') || msg.includes('reopen')
              ? 'Table not active. Ask your waiter to open the table.'
              : 'Invalid QR code. Please ask your waiter.'
          );
          setStep('error');
          return;
        }

        setTableId(data.table_id);
        setOutletId(data.outlet_id);
        const tableZone = data.zone || 'normal';
        setZone(tableZone);
        localStorage.setItem('table_zone', tableZone);

        // Repeat customer: already identified for this QR session → go straight to menu
        if (localStorage.getItem(`guest_${slug}`)) {
          goToMenu(data.outlet_id, data.table_id, tableZone);
          return;
        }

        setStep('login');
      } catch {
        setErrorMsg('Could not connect to server. Please try again.');
        setStep('error');
      }
    })();
  }, [slug, goToMenu]);

  const handleStartOrdering = () => {
    if (phone.length !== 10 || !/^\d{10}$/.test(phone)) {
      setPhoneError('Enter a valid 10-digit phone number');
      return;
    }
    // Store guest identity keyed to this QR session slug
    localStorage.setItem(`guest_${slug}`, JSON.stringify({ phone: `+91${phone}`, at: Date.now() }));
    goToMenu(outletId, tableId, zone);
  };

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

  return (
    <Wrapper>
      <Header />
      <p style={{ textAlign: 'center', color: '#6b7280', fontSize: 15, marginBottom: 24, lineHeight: 1.5 }}>
        Welcome to Rudrarthi!<br />
        <span style={{ fontSize: 13 }}>Enter your phone number to start ordering.</span>
      </p>

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
            onKeyDown={e => { if (e.key === 'Enter') handleStartOrdering(); }}
            placeholder="9876543210"
            maxLength={10}
            autoFocus
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

      <PrimaryButton onClick={handleStartOrdering} disabled={phone.length !== 10}>
        Start Ordering →
      </PrimaryButton>

      <p style={{ textAlign: 'center', color: '#9ca3af', fontSize: 11, marginTop: 12 }}>
        Your number is only used to keep track of your order.
      </p>
    </Wrapper>
  );
}
