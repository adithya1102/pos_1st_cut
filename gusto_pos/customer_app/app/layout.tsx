import type { Metadata, Viewport } from "next";
import "./globals.css";
import { CartProvider } from "@/lib/cart-store";

export const metadata: Metadata = {
  title: "Gusto - Order Food",
  description: "Scan, Order, Enjoy — Dine-in ordering by Gusto POS",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#0f172a",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-[#0f172a] text-[#f8fafc] antialiased">
        <CartProvider>{children}</CartProvider>
      </body>
    </html>
  );
}
