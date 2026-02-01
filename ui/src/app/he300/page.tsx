"use client";

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function HE300Redirect() {
  const router = useRouter();

  useEffect(() => {
    // Redirect to main page - the benchmark tab is the default
    router.replace('/');
  }, [router]);

  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500 mx-auto"></div>
        <p className="mt-4 text-gray-600">Redirecting to HE-300 Benchmark...</p>
      </div>
    </div>
  );
}
