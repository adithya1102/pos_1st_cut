import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Same fix as gusto_pos/customer_app: a stray package-lock.json above this
  // directory makes Turbopack infer the wrong workspace root and break module
  // resolution (e.g. tailwindcss). Pin the root explicitly.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
