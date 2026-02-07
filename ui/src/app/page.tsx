"use client";

import React, { useEffect, useState } from "react";
import { useSession, signIn, signOut } from "next-auth/react";
import AuditLogs from "../components/AuditLogs";
import DiscordTab from "../components/DiscordTab";
import WiseAuthorityTab from "../components/WiseAuthorityTab";
import AdminTab from "../components/AdminTab";
import Head from "next/head";
import Link from "next/link";

export default function Home() {
  const { data: session } = useSession();
  const [role, setRole] = useState<string | null>(null);
  const [groups, setGroups] = useState<string[]>([]);

  useEffect(() => {
    if (!session) {
      setRole(null);
      setGroups([]);
      return;
    }
    const email = session?.user?.email;
    if (!email) return;
    const fetchUserInfo = async () => {
      try {
        const res = await fetch(
          "/api/auth/me",
          {
            headers: {
              "x-user-email": email,
            },
          }
        );
        if (res.ok) {
          const me = await res.json();
          setRole(me.role);
          setGroups((me.groups || "").split(",").map((g: string) => g.trim()).filter(Boolean));
        } else {
          setRole(null);
          setGroups([]);
        }
      } catch {
        setRole(null);
        setGroups([]);
      }
    };
    fetchUserInfo();
  }, [session]);

  return (
    <>
      <Head>
        <title>CIRIS NODE0</title>
      </Head>
      <div className="min-h-screen bg-gray-100 flex flex-col items-center justify-center">
        <header className="bg-white shadow w-full">
          <div className="max-w-3xl mx-auto py-8 px-4 sm:px-6 lg:px-8 text-center">
            <h1 className="text-4xl font-extrabold text-gray-900 mb-2">
              Welcome to the CIRIS.AI Alignment and Human Oversight Server
            </h1>
            <p className="text-lg text-gray-700 mb-4">
              Visit{" "}
              <a
                href="https://ciris.ai"
                className="text-blue-600 underline hover:text-blue-800"
                target="_blank"
                rel="noopener noreferrer"
              >
                ciris.ai
              </a>{" "}
              for more information.
            </p>
            {/* --- TOP NAVIGATION TABS --- */}
            <nav className="flex flex-wrap justify-center gap-2 mb-4 border-b border-gray-200 pb-2">
              <Link href="/" className="px-4 py-2 rounded-t bg-gray-100 hover:bg-indigo-100 text-indigo-700 font-semibold">Home</Link>
              <Link href="/he300" className="px-4 py-2 rounded-t bg-indigo-600 hover:bg-indigo-700 text-white font-semibold">⚖️ HE-300 Benchmark</Link>
              <Link href="#audit" className="px-4 py-2 rounded-t bg-gray-100 hover:bg-indigo-100 text-indigo-700 font-semibold">Audit Logs</Link>
              <Link href="#admin" className="px-4 py-2 rounded-t bg-gray-100 hover:bg-indigo-100 text-indigo-700 font-semibold">Admin</Link>
              <Link href="#wise" className="px-4 py-2 rounded-t bg-gray-100 hover:bg-indigo-100 text-indigo-700 font-semibold">Wise Authority</Link>
              <Link href="#discord" className="px-4 py-2 rounded-t bg-gray-100 hover:bg-indigo-100 text-indigo-700 font-semibold">Discord</Link>
              <Link href="#test" className="px-4 py-2 rounded-t bg-gray-100 hover:bg-indigo-100 text-indigo-700 font-semibold">Test Connection</Link>
              <Link href="#bench" className="px-4 py-2 rounded-t bg-gray-100 hover:bg-indigo-100 text-indigo-700 font-semibold">Bench</Link>
              <Link href="#health" className="px-4 py-2 rounded-t bg-gray-100 hover:bg-indigo-100 text-indigo-700 font-semibold">Health</Link>
            </nav>
            {/* --- END NAVIGATION --- */}
            <div className="flex flex-col sm:flex-row justify-center gap-4 mb-4">
              <button
                onClick={() => signIn("discord")}
                className="inline-flex items-center px-6 py-3 bg-indigo-600 text-white text-lg font-semibold rounded-lg shadow hover:bg-indigo-700 transition"
              >
                <svg
                  className="w-6 h-6 mr-2"
                  fill="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path d="M20.317 4.369a19.791 19.791 0 00-4.885-1.515.07.07 0 00-.073.035c-.211.375-.444.864-.608 1.249-1.844-.276-3.68-.276-5.486 0-.164-.393-.405-.874-.617-1.249a.07.07 0 00-.073-.035 19.736 19.736 0 00-4.885 1.515.064.064 0 00-.03.027C.533 9.045-.32 13.579.099 18.057a.08.08 0 00.031.056c2.052 1.507 4.042 2.422 5.992 3.029a.077.077 0 00.084-.027c.461-.63.873-1.295 1.226-1.994a.076.076 0 00-.041-.104c-.652-.247-1.27-.549-1.872-.892a.077.077 0 01-.008-.127c.126-.094.252-.192.372-.291a.074.074 0 01.077-.01c3.927 1.793 8.18 1.793 12.061 0a.073.073 0 01.078.009c.12.099.246.197.372.291a.077.077 0 01-.006.127 12.298 12.298 0 01-1.873.892.076.076 0 00-.04.105c.36.699.772 1.364 1.225 1.994a.076.076 0 00.084.028c1.95-.607 3.94-1.522 5.992-3.029a.077.077 0 00.031-.055c.5-5.177-.838-9.673-3.548-13.661a.061.061 0 00-.03-.028zM8.02 15.331c-1.183 0-2.156-1.085-2.156-2.419 0-1.333.955-2.418 2.156-2.418 1.21 0 2.175 1.094 2.156 2.418 0 1.334-.955 2.419-2.156 2.419zm7.974 0c-1.183 0-2.156-1.085-2.156-2.419 0-1.333.955-2.418 2.156-2.418 1.21 0 2.175 1.094 2.156 2.418 0 1.334-.946 2.419-2.156 2.419z" />
                </svg>
                Login with Discord
              </button>
              <button
                onClick={() => signIn("google")}
                className="inline-flex items-center px-6 py-3 bg-red-600 text-white text-lg font-semibold rounded-lg shadow hover:bg-red-700 transition"
              >
                <svg className="w-6 h-6 mr-2" viewBox="0 0 48 48">
                  <g>
                    <path fill="#4285F4" d="M24 9.5c3.54 0 6.44 1.22 8.41 3.22l6.24-6.24C34.64 2.61 29.8 0 24 0 14.82 0 6.88 5.82 2.69 14.09l7.25 5.63C12.01 13.09 17.55 9.5 24 9.5z"/>
                    <path fill="#34A853" d="M46.1 24.55c0-1.64-.15-3.21-.42-4.73H24v9.18h12.42c-.54 2.91-2.18 5.38-4.66 7.04l7.25 5.63C43.98 37.13 46.1 31.3 46.1 24.55z"/>
                    <path fill="#FBBC05" d="M10.94 28.72A14.5 14.5 0 019.5 24c0-1.64.28-3.22.78-4.72l-7.25-5.63A23.94 23.94 0 000 24c0 3.77.9 7.34 2.5 10.45l8.44-6.73z"/>
                    <path fill="#EA4335" d="M24 46c6.48 0 11.92-2.15 15.89-5.85l-7.25-5.63c-2.01 1.35-4.6 2.16-8.64 2.16-6.45 0-11.99-3.59-14.06-8.72l-8.44 6.73C6.88 42.18 14.82 48 24 48z"/>
                    <path fill="none" d="M0 0h48v48H0z"/>
                  </g>
                </svg>
                Login with Google
              </button>
              {session && (
                <button
                  onClick={() => signOut()}
                  className="inline-flex items-center px-6 py-3 bg-gray-300 text-gray-800 text-lg font-semibold rounded-lg shadow hover:bg-gray-400 transition"
                >
                  Logout
                </button>
              )}
            </div>
          </div>
        </header>
        <main className="w-full">
          <div className="max-w-4xl mx-auto py-6 sm:px-6 lg:px-8">
            {/* Debug Panel: Show session and user info */}
            <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded text-yellow-900">
              <h3 className="font-bold mb-2">Debug: Session & User Info</h3>
              <pre className="text-xs overflow-x-auto bg-yellow-100 p-2 rounded">
{JSON.stringify({ session, role, groups }, null, 2)}
              </pre>
              {!session && <div className="text-red-600">Not logged in (anonymous)</div>}
              {session && !role && (
                <div className="text-orange-600">Logged in, but no role/group assigned. Contact admin to be added to a group/role.</div>
              )}
            </div>
            <div className="px-4 py-6 sm:px-0 space-y-8">
              <div id="audit"><AuditLogs /></div>
              <div id="admin"><AdminTab /></div>
              <div id="wise"><WiseAuthorityTab /></div>
              <div id="discord"><DiscordTab /></div>
              <div id="test">{/* TODO: import and render TestConnection component here */}</div>
              <div id="bench">{/* TODO: import and render Bench/SimpleBenchRunner component here */}</div>
              <div id="health">{/* TODO: import and render HealthStatus component here */}</div>
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
