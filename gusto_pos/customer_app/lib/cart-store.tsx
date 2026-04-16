'use client';

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { CartItem } from './types';

function parseAddonPrice(option: string): number {
  const match = option.match(/\+₹(\d+)/);
  return match ? parseInt(match[1], 10) : 0;
}

function calcItemTotal(price: number, quantity: number, customizations: string[]): number {
  const addonTotal = customizations.reduce((sum, c) => sum + parseAddonPrice(c), 0);
  return (price + addonTotal) * quantity;
}

function customizationKey(customizations: string[]): string {
  return [...customizations].sort().join('|');
}

interface CartContextType {
  items: CartItem[];
  outletId: string;
  tableId: string;
  setOutletId: (id: string) => void;
  setTableId: (id: string) => void;
  addItem: (
    id: string,
    name: string,
    price: number,
    is_veg: boolean,
    customizations: string[],
    custom_note: string,
    quantity: number
  ) => void;
  removeItem: (index: number) => void;
  increaseQuantity: (index: number) => void;
  decreaseQuantity: (index: number) => void;
  clearCart: () => void;
  totalItems: number;
  totalAmount: number;
}

const CartContext = createContext<CartContextType | null>(null);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<CartItem[]>([]);
  const [outletId, setOutletId] = useState(
    process.env.NEXT_PUBLIC_OUTLET_ID || '0b8a8349-6144-41a8-b028-b9089bd8eaea'
  );
  const [tableId, setTableId] = useState('1');

  // Persist cart to localStorage
  useEffect(() => {
    const saved = localStorage.getItem('gusto_cart');
    if (saved) {
      try {
        setItems(JSON.parse(saved));
      } catch {
        // ignore
      }
    }
  }, []);

  useEffect(() => {
    localStorage.setItem('gusto_cart', JSON.stringify(items));
  }, [items]);

  const addItem = useCallback(
    (
      id: string,
      name: string,
      price: number,
      is_veg: boolean,
      customizations: string[],
      custom_note: string,
      quantity: number
    ) => {
      setItems((prev) => {
        const key = `${id}:${customizationKey(customizations)}:${custom_note}`;
        const existing = prev.findIndex(
          (item) =>
            `${item.id}:${customizationKey(item.customizations)}:${item.custom_note}` === key
        );
        if (existing !== -1) {
          const updated = [...prev];
          const newQty = updated[existing].quantity + quantity;
          updated[existing] = {
            ...updated[existing],
            quantity: newQty,
            item_total: calcItemTotal(price, newQty, customizations),
          };
          return updated;
        }
        return [
          ...prev,
          {
            id,
            name,
            price,
            quantity,
            is_veg,
            customizations,
            custom_note,
            item_total: calcItemTotal(price, quantity, customizations),
          },
        ];
      });
    },
    []
  );

  const removeItem = useCallback((index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const increaseQuantity = useCallback((index: number) => {
    setItems((prev) => {
      const updated = [...prev];
      const item = updated[index];
      updated[index] = {
        ...item,
        quantity: item.quantity + 1,
        item_total: calcItemTotal(item.price, item.quantity + 1, item.customizations),
      };
      return updated;
    });
  }, []);

  const decreaseQuantity = useCallback((index: number) => {
    setItems((prev) => {
      const updated = [...prev];
      const item = updated[index];
      if (item.quantity <= 1) {
        return updated.filter((_, i) => i !== index);
      }
      updated[index] = {
        ...item,
        quantity: item.quantity - 1,
        item_total: calcItemTotal(item.price, item.quantity - 1, item.customizations),
      };
      return updated;
    });
  }, []);

  const clearCart = useCallback(() => {
    setItems([]);
    localStorage.removeItem('gusto_cart');
  }, []);

  const totalItems = items.reduce((sum, item) => sum + item.quantity, 0);
  const totalAmount = items.reduce((sum, item) => sum + item.item_total, 0);

  return (
    <CartContext.Provider
      value={{
        items,
        outletId,
        tableId,
        setOutletId,
        setTableId,
        addItem,
        removeItem,
        increaseQuantity,
        decreaseQuantity,
        clearCart,
        totalItems,
        totalAmount,
      }}
    >
      {children}
    </CartContext.Provider>
  );
}

export function useCart() {
  const context = useContext(CartContext);
  if (!context) throw new Error('useCart must be used within CartProvider');
  return context;
}
