import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Gusto Admin",
  description: "Internal platform admin dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
