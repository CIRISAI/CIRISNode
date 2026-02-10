"use client";

import { useSession } from "next-auth/react";
import { ReactNode } from "react";

interface RoleGuardProps {
  allowed: string[];
  children: ReactNode;
}

export default function RoleGuard({ allowed, children }: RoleGuardProps) {
  const { data: session, status } = useSession();

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center py-20 text-gray-500">
        Loading...
      </div>
    );
  }

  const role = session?.user?.role || "anonymous";

  if (!allowed.includes(role)) {
    return (
      <div className="flex flex-col items-center justify-center py-20 space-y-3">
        <div className="text-red-600 font-semibold text-lg">Access Denied</div>
        <p className="text-gray-500 text-sm">
          You do not have permission to view this page.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
