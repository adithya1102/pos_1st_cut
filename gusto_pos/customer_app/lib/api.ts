export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://192.168.1.7:8000';

const DEFAULT_MENU_ID = process.env.NEXT_PUBLIC_MENU_ID || 'dc88b6a6-129c-479f-8609-07b8525f4310';

export async function fetchMenu(menuId: string = DEFAULT_MENU_ID) {
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
