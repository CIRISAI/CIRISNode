"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

interface NavItem {
  href: string;
  label: string;
  roles: string[]; // which roles can see this nav item
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Scores", roles: ["admin", "wise_authority"] },
  { href: "/frontier", label: "Frontier Sweep", roles: ["admin"] },
  { href: "/evaluations", label: "Evaluations", roles: ["admin", "wise_authority"] },
  { href: "/oversight", label: "Agent Oversight", roles: ["admin", "wise_authority"] },
  { href: "/audit", label: "Audit", roles: ["admin", "wise_authority"] },
  { href: "/system", label: "System", roles: ["admin"] },
  { href: "/users", label: "Users", roles: ["admin"] },
];

const ROLE_LABELS: Record<string, { label: string; color: string }> = {
  admin: { label: "Root", color: "bg-red-600" },
  wise_authority: { label: "Authority", color: "bg-amber-600" },
};

export default function AdminNav() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const [pendingCount, setPendingCount] = useState(0);

  const role = session?.user?.role || "anonymous";

  // Poll for pending WBD task count
  useEffect(() => {
    if (!session) return;
    let cancelled = false;

    const fetchCount = async () => {
      try {
        const data = await apiFetch<{ tasks: { status: string }[] }>(
          "/api/v1/wbd/tasks?state=open"
        );
        if (!cancelled) {
          setPendingCount(data.tasks?.length || 0);
        }
      } catch {
        // Ignore fetch errors for badge count
      }
    };

    fetchCount();
    const interval = setInterval(fetchCount, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [session]);

  const visibleItems = NAV_ITEMS.filter((item) => item.roles.includes(role));
  const roleInfo = ROLE_LABELS[role];

  return (
    <nav className="bg-gray-900 border-b border-gray-800">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-1">
            <span className="text-white font-bold text-lg mr-6">
              CIRISNode Admin
            </span>
            {visibleItems.map(({ href, label }) => {
              const active =
                href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`px-3 py-2 rounded text-sm font-medium transition-colors relative ${
                    active
                      ? "bg-gray-700 text-white"
                      : "text-gray-300 hover:bg-gray-800 hover:text-white"
                  }`}
                >
                  {label}
                  {label === "Agent Oversight" && pendingCount > 0 && (
                    <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center font-bold">
                      {pendingCount > 9 ? "9+" : pendingCount}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
          <div className="flex items-center gap-3">
            {roleInfo && (
              <span
                className={`text-xs px-2 py-0.5 rounded text-white font-medium ${roleInfo.color}`}
              >
                {roleInfo.label}
              </span>
            )}
            {session?.user?.email && (
              <span className="text-gray-400 text-sm">
                {session.user.email}
              </span>
            )}
            {session && (
              <button
                onClick={() => signOut()}
                className="text-gray-400 hover:text-white text-sm transition-colors"
              >
                Sign out
              </button>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
