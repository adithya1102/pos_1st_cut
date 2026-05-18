'use client';

import { Suspense, useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { useCart } from '@/lib/cart-store';
import { Menu, MenuCategory, MenuItem } from '@/lib/types';
import { API_BASE } from '@/lib/api';
import MenuItemCard from '@/components/MenuItemCard';
import CustomizationModal from '@/components/CustomizationModal';
import CartBar from '@/components/CartBar';

function MenuLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0f172a]">
      <div className="flex flex-col items-center gap-4">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#f97316] border-t-transparent" />
        <p className="text-sm text-slate-400">Loading menu...</p>
      </div>
    </div>
  );
}

export default function MenuPage() {
  return (
    <Suspense fallback={<MenuLoading />}>
      <MenuContent />
    </Suspense>
  );
}

function MenuContent() {
  const searchParams = useSearchParams();
  const { addItem, setOutletId, setTableId } = useCart();

  const [menu, setMenu] = useState<Menu | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>('');
  const [modalItem, setModalItem] = useState<MenuItem | null>(null);

  // Resolved from backend — never from URL params
  const [resolvedOutletId, setResolvedOutletId] = useState<string>('');
  const [resolvedZone, setResolvedZone] = useState<string>('normal');
  const [tokenValid, setTokenValid] = useState<boolean | null>(null);
  const [tokenMessage, setTokenMessage] = useState<string>('');
  const [validatedTableId, setValidatedTableId] = useState<string>('');

  const categoryRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const tabContainerRef = useRef<HTMLDivElement>(null);

  // Resolve table context from backend — zone and outlet are never read from URL params
  useEffect(() => {
    const t = searchParams.get('t');         // static QR token (printed on table)
    const token = searchParams.get('token'); // legacy dynamic session token

    if (t) {
      // Secure path: resolve static QR token; backend returns outlet_id + zone authoritatively
      fetch(`${API_BASE}/api/v1/tables/resolve?t=${encodeURIComponent(t)}`)
        .then((res) => {
          if (!res.ok) throw new Error(`resolve ${res.status}`);
          return res.json();
        })
        .then((data) => {
          const z = data.zone || 'normal';
          setResolvedOutletId(data.outlet_id);
          setResolvedZone(z);
          setValidatedTableId(data.table_name || '');
          setOutletId(data.outlet_id);
          setTableId(data.table_name || '');
          localStorage.setItem('table_zone', z);
          setTokenValid(true);
        })
        .catch((err) => {
          console.error('Token resolve error:', err);
          setTokenValid(false);
          setTokenMessage('Invalid QR code. Please scan the code on your table.');
          setLoading(false);
        });
      return;
    }

    if (token) {
      // Legacy path: validate dynamic session token
      fetch(`${API_BASE}/api/v1/tables/validate/${token}`)
        .then((res) => {
          if (!res.ok) throw new Error(`Validate ${res.status}`);
          return res.json();
        })
        .then((data) => {
          if (data.is_valid) {
            const z = data.zone || 'normal';
            setResolvedOutletId(data.outlet_id || '');
            setResolvedZone(z);
            setValidatedTableId(data.table_id || '');
            setOutletId(data.outlet_id || '');
            setTableId(data.table_id || '');
            localStorage.setItem('table_zone', z);
            setTokenValid(true);
          } else {
            setTokenValid(false);
            setTokenMessage(data.message || 'Invalid or expired QR code.');
            setLoading(false);
          }
        })
        .catch((err) => {
          console.error('Token validation error:', err);
          setTokenValid(false);
          setTokenMessage('Could not connect to server. Please try again.');
          setLoading(false);
        });
      return;
    }

    // No token present at all
    setTokenValid(false);
    setTokenMessage('No table token provided. Please scan the QR code at your table.');
    setLoading(false);
  }, [searchParams, setOutletId, setTableId]);

  // Fetch menu once token is resolved — zone and outlet come from state, not URL
  useEffect(() => {
    if (tokenValid === false || tokenValid === null) return;
    if (!resolvedOutletId) return;

    setLoading(true);
    fetch(`${API_BASE}/api/v1/menus/zone/${resolvedOutletId}/${resolvedZone}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Menu fetch failed: ${res.status} ${res.statusText}`);
        return res.json();
      })
      .then((data) => {
        if (!data || typeof data !== 'object') throw new Error('Menu response is not a valid object');
        setMenu({
          zone: data.zone || resolvedZone,
          categories: Array.isArray(data.categories) ? data.categories : [],
          id: data.id,
          outlet_id: data.outlet_id,
          version_label: data.version_label,
        });
        const cats = Array.isArray(data.categories) ? data.categories : [];
        if (cats.length > 0) setActiveCategory(cats[0].id);
      })
      .catch((err) => {
        console.error('Menu fetch error:', err);
        setError(err.message || 'Unknown error loading menu');
      })
      .finally(() => setLoading(false));
  }, [tokenValid, resolvedOutletId, resolvedZone]);

  const handleAddItem = (item: MenuItem) => {
    setModalItem(item);
  };

  const handleCustomizationConfirm = (
    item: MenuItem,
    customizations: string[],
    customNote: string,
    quantity: number
  ) => {
    const itemPrice = item.price ?? item.base_price ?? 0;
    addItem(item.id, item.name, itemPrice, item.is_veg, customizations, customNote, quantity);
    setModalItem(null);
  };

  const scrollToCategory = (categoryId: string) => {
    setActiveCategory(categoryId);
    const el = categoryRefs.current[categoryId];
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0f172a]">
        <div className="flex flex-col items-center gap-4">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#f97316] border-t-transparent" />
          <p className="text-sm text-slate-400">
            {tokenValid === null ? 'Validating table token...' : 'Loading menu...'}
          </p>
        </div>
      </div>
    );
  }

  // Show token error if token validation failed
  if (tokenValid === false) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0f172a] p-4">
        <div className="text-center max-w-md">
          <div className="text-6xl mb-4">🚫</div>
          <p className="text-lg font-semibold text-[#ef4444]">Access Denied</p>
          <p className="mt-2 text-sm text-slate-400">{tokenMessage}</p>
          <p className="mt-4 text-xs text-slate-500">
            Please ask your server for a valid QR code to access the menu.
          </p>
        </div>
      </div>
    );
  }

  if (error || !menu) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0f172a]">
        <div className="text-center">
          <p className="text-lg font-semibold text-[#ef4444]">Failed to load menu</p>
          <p className="mt-2 text-sm text-slate-400">{error || 'Unknown error'}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 rounded-lg bg-[#f97316] px-4 py-2 text-sm font-medium text-white"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const categories: MenuCategory[] = menu.categories || [];
  const zone = menu.zone || resolvedZone;

  return (
    <div className="min-h-screen bg-[#0f172a] pb-24">
      {/* Header */}
      <div className="sticky top-0 z-30 bg-[#0f172a]/95 backdrop-blur-sm">
        <div className="mx-auto max-w-md px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-[#f8fafc]">
                🍽️ <span className="text-[#f97316]">Rudrarthi</span> Menu
              </h1>
              <p className="mt-0.5 text-xs text-slate-500">
                Table {validatedTableId || searchParams.get('table_id') || '1'}
              </p>
            </div>
          </div>
        </div>

        {/* Category tabs */}
        <div
          ref={tabContainerRef}
          className="flex gap-2 overflow-x-auto px-4 pb-3 scrollbar-hide"
        >
          {categories.map((cat) => (
            <button
              key={cat.id}
              onClick={() => scrollToCategory(cat.id)}
              className={`shrink-0 rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
                activeCategory === cat.id
                  ? 'bg-[#f97316] text-white'
                  : 'bg-[#1e293b] text-slate-400 hover:text-slate-200'
              }`}
            >
              {cat.name}
            </button>
          ))}
        </div>
      </div>

      {/* Menu items by category */}
      <div className="mx-auto max-w-md px-4">
        {categories.map((cat) => {
          const activeItems = (cat.items || []).filter(
            (item) => item.is_available !== false && item.is_active !== false
          );
          if (activeItems.length === 0) return null;
          return (
            <div
              key={cat.id}
              ref={(el) => { categoryRefs.current[cat.id] = el; }}
              className="pt-6"
            >
              <h2 className="mb-3 text-base font-bold text-slate-300">{cat.name}</h2>
              <div className="space-y-3">
                {activeItems.map((item) => (
                  <MenuItemCard key={item.id} item={item} onAdd={handleAddItem} />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <CartBar />

      {modalItem && (
        <CustomizationModal
          item={modalItem}
          onConfirm={handleCustomizationConfirm}
          onClose={() => setModalItem(null)}
        />
      )}
    </div>
  );
}