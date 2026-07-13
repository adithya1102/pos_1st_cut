import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // A stray package-lock.json at C:\Users\Adithya made Turbopack infer the
  // wrong workspace root, breaking module resolution (e.g. tailwindcss).
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
