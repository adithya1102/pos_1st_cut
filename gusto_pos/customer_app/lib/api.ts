import { API_BASE, MENU_ID } from './config';

export { API_BASE };

// No callers as of this writing — kept because it is an exported entry point.
// If it stays unused, deleting it also drops the NEXT_PUBLIC_MENU_ID requirement.
export async function fetchMenu(menuId: string = MENU_ID) {
  const res = await fetch(`${API_BASE}/api/v1/menus/${menuId}`);
  if (!res.ok) throw new Error('Failed to fetch menu');
  return res.json();
}

export async function fetchMenuByZone(outletId: string, zone: string) {
  const res = await fetch(`${API_BASE}/api/v1/menus/zone/${outletId}/${zone}`);
  if (!res.ok) throw new Error('Failed to fetch menu');
  return res.json();
}

export async function createOrder(orderData: {
  outlet_id: string;
  table_id: string;
  total_amount: number;
  order_type: string;
  zone: string;
  source: string;
  items: {
    name: string;
    quantity: number;
    unit_price: number;
    customizations: string[];
    custom_note: string;
  }[];
}) {
  const res = await fetch(`${API_BASE}/api/v1/orders/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(orderData),
  });
  if (!res.ok) throw new Error('Failed to create order');
  return res.json();
}

export async function fetchOrder(orderId: string) {
  const res = await fetch(`${API_BASE}/api/v1/orders/${orderId}`);
  if (!res.ok) throw new Error('Failed to fetch order');
  return res.json();
}
