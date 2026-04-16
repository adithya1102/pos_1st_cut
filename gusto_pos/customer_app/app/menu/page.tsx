'use client';

import { Suspense, useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { useCart } from '@/lib/cart-store';
import { Menu, MenuCategory, MenuItem } from '@/lib/types';
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
  
  // Token validation states
  const [tokenValid, setTokenValid] = useState<boolean | null>(null);
  const [tokenMessage, setTokenMessage] = useState<string>('');
  const [validatedTableId, setValidatedTableId] = useState<string>('');

  const categoryRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const tabContainerRef = useRef<HTMLDivElement>(null);

  // Validate token on load
  useEffect(() => {
    const token = searchParams.get('token');
    const outletIdParam = searchParams.get('outlet_id');
    const tableIdParam = searchParams.get('table_id');

    if (!token) {
      // Allow direct access via outlet_id + table_id query params
      if (outletIdParam && tableIdParam) {
        setOutletId(outletIdParam);
        setTableId(tableIdParam);
        setValidatedTableId(tableIdParam);
        setTokenValid(true);
        return;
      }
      // No token and no direct params - show error
      setTokenValid(false);
      setTokenMessage('No table token provided. Please scan the QR code at your table.');
      setLoading(false);
      return;
    }

    // Validate token with backend
    fetch(`http://192.168.1.4:8000/api/v1/tables/validate/${token}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.is_valid) {
          setTokenValid(true);
          setValidatedTableId(data.table_id);
          setOutletId(data.outlet_id);
          setTableId(data.table_id);
        } else {
          setTokenValid(false);
          setTokenMessage(data.message || 'Invalid or expired QR code.');
        }
      })
      .catch(() => {
        setTokenValid(false);
        setTokenMessage('Could not connect to server. Please try again.');
      })
      .finally(() => {
        // Only set loading to false after token validation is complete
      });
  }, [searchParams, setOutletId, setTableId]);

  // Read query params (legacy support)
  useEffect(() => {
    const outletId = searchParams.get('outlet_id') || process.env.NEXT_PUBLIC_OUTLET_ID || '';
    const tableId = searchParams.get('table_id') || '1';
    // Only use these if token validation hasn't set them
    if (!validatedTableId) {
      if (outletId) setOutletId(outletId);
      setTableId(tableId);
    }
  }, [searchParams, setOutletId, setTableId, validatedTableId]);

  // Fetch menu (only if token is valid)
  useEffect(() => {
    if (tokenValid === false) {
      setLoading(false);
      return;
    }
    if (tokenValid === null) {
      // Still validating token
      return;
    }

    const zone = searchParams.get('zone') || localStorage.getItem('table_zone') || 'normal';
    const outletIdForMenu = searchParams.get('outlet_id') || process.env.NEXT_PUBLIC_OUTLET_ID || '';
    setLoading(true);
    fetch(`http://192.168.1.4:8000/api/v1/menus/zone/${outletIdForMenu}/${zone}`)
      .then((res) => { if (!res.ok) throw new Error('Failed to fetch menu'); return res.json(); })
      .then((data) => {
        setMenu(data);
        if (data.categories?.length > 0) {
          setActiveCategory(data.categories[0].id);
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [searchParams, tokenValid]);

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
  const zone = menu.zone || searchParams.get('zone') || 'normal';

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
            {/* Zone badge */}
            {zone === 'ac' ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-600 px-3 py-1 text-xs font-semibold text-white">
                ❄️ AC DINING
              </span>
            ) : (
              <span className="inline-flex items-center rounded-full bg-gray-500 px-3 py-1 text-xs font-semibold text-white">
                REGULAR DINING
              </span>
            )}
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
              ref={(el) => {
                categoryRefs.current[cat.id] = el;
              }}
              className="mb-6 scroll-mt-28"
            >
              <h2 className="mb-3 text-sm font-semibold text-slate-400 uppercase tracking-wider">
                {cat.name}{' '}
                <span className="text-xs text-slate-600">({activeItems.length})</span>
              </h2>
              <div className="space-y-3">
                {activeItems.map((item) => (
                  <MenuItemCard key={item.id} item={item} onAdd={handleAddItem} />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Cart bottom bar */}
      <CartBar />

      {/* Customization modal */}
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


