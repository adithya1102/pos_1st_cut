export interface MenuModifier {
  id: string;
  modifier_name: string;
  extra_price: number;
}

export interface MenuItem {
  id: string;
  name: string;
  price: number;
  is_veg: boolean;
  is_available: boolean;
  customization_options: string[];
  short_code?: string;
  base_price?: number;
  is_active?: boolean;
  modifiers?: MenuModifier[];
}

export interface MenuCategory {
  id: string;
  name: string;
  items: MenuItem[];
}

export interface Menu {
  zone: string;
  categories: MenuCategory[];
  id?: string;
  outlet_id?: string;
  version_label?: string;
}

export interface CartItem {
  id: string;
  name: string;
  price: number;
  quantity: number;
  is_veg: boolean;
  customizations: string[];
  custom_note: string;
  item_total: number;
}

export interface Order {
  id: string;
  readable_id: number;
  kitchen_token: string;
  order_status: string;
  total_amount: number;
  outlet_id: string;
}

export type OrderStatus =
  | 'pending'
  | 'confirmed'
  | 'in_kitchen'
  | 'ready'
  | 'served'
  | 'completed'
  | 'cancelled';
