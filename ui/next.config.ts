import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: 'http://api:8000/api/v1/:path*', // Proxy to backend API only
      },
    ];
  },
};

export default nextConfig;
