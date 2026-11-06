import type { NextConfig } from "next";

const isNextDev = process.env.NODE_ENV === "development" || process.argv.includes("dev");
const apiUrl = isNextDev
  ? "http://localhost:8000"
  : process.env.NEXT_PUBLIC_API_URL || (process.env.BMA_DESKTOP_BUILD === "1" ? "/api/desktop" : "http://localhost:8000");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  env: { NEXT_PUBLIC_API_URL: apiUrl },
  ...(isNextDev ? { distDir: ".next-dev" } : {}),
  ...(process.env.BMA_DESKTOP_BUILD === "1" && !isNextDev ? {
    output: process.env.BMA_DESKTOP_OUTPUT === "standalone" ? "standalone" as const : "export" as const,
    distDir: ".next-desktop",
    trailingSlash: true,
    images: { unoptimized: true },
    typescript: { tsconfigPath: "tsconfig.desktop.json" },
  } : {}),
};

export default nextConfig;
