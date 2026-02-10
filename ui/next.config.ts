import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    unoptimized: true,
  },
  env: {
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL || "https://node.ciris.ai",
  },
  // In Docker (dev), proxy /api/v1/* to the backend container.
  // In Cloudflare Workers, the frontend calls NEXT_PUBLIC_API_URL directly.
  ...(process.env.NODE_ENV === "development" && !process.env.CLOUDFLARE_WORKERS
    ? {
        async rewrites() {
          return [
            {
              source: "/api/v1/:path*",
              destination: "http://api:8000/api/v1/:path*",
            },
          ];
        },
      }
    : {}),
};

export default nextConfig;
