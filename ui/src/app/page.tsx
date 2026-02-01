"use client";

import React, { useEffect, useState } from "react";
import { useSession, signIn, signOut } from "next-auth/react";
import AuditLogs from "../components/AuditLogs";
import DiscordTab from "../components/DiscordTab";
import WiseAuthorityTab from "../components/WiseAuthorityTab";
import AdminTab from "../components/AdminTab";
import HE300Content from "../components/HE300Content";

type MainTab = 'benchmark' | 'audit' | 'admin' | 'wise' | 'discord';

export default function Home() {
  const { data: session } = useSession();
  const [role, setRole] = useState<string | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<MainTab>('benchmark');
  const [showDebug, setShowDebug] = useState(false);

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
        const res = await fetch("/api/auth/me", {
          headers: { "x-user-email": email },
        });
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

  const mainTabs = [
    { id: 'benchmark' as const, label: 'HE-300 Benchmark', icon: '⚖️' },
    { id: 'audit' as const, label: 'Audit Logs', icon: '📋' },
    { id: 'admin' as const, label: 'Admin', icon: '👤' },
    { id: 'wise' as const, label: 'Wise Authority', icon: '🦉' },
    { id: 'discord' as const, label: 'Discord', icon: '💬' },
  ];

  return (
    <div className="min-h-screen bg-gray-100 flex flex-col">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                CIRIS.AI Alignment Node
              </h1>
              <p className="text-sm text-gray-600 mt-1">
                Human Oversight & Ethics Benchmark Server
              </p>
            </div>
            <div className="flex items-center gap-3">
              {!session ? (
                <>
                  <button
                    onClick={() => signIn("discord")}
                    className="inline-flex items-center px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg shadow hover:bg-indigo-700 transition"
                  >
                    <svg className="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M20.317 4.369a19.791 19.791 0 00-4.885-1.515.07.07 0 00-.073.035c-.211.375-.444.864-.608 1.249-1.844-.276-3.68-.276-5.486 0-.164-.393-.405-.874-.617-1.249a.07.07 0 00-.073-.035 19.736 19.736 0 00-4.885 1.515.064.064 0 00-.03.027C.533 9.045-.32 13.579.099 18.057a.08.08 0 00.031.056c2.052 1.507 4.042 2.422 5.992 3.029a.077.077 0 00.084-.027c.461-.63.873-1.295 1.226-1.994a.076.076 0 00-.041-.104c-.652-.247-1.27-.549-1.872-.892a.077.077 0 01-.008-.127c.126-.094.252-.192.372-.291a.074.074 0 01.077-.01c3.927 1.793 8.18 1.793 12.061 0a.073.073 0 01.078.009c.12.099.246.197.372.291a.077.077 0 01-.006.127 12.298 12.298 0 01-1.873.892.076.076 0 00-.04.105c.36.699.772 1.364 1.225 1.994a.076.076 0 00.084.028c1.95-.607 3.94-1.522 5.992-3.029a.077.077 0 00.031-.055c.5-5.177-.838-9.673-3.548-13.661a.061.061 0 00-.03-.028zM8.02 15.331c-1.183 0-2.156-1.085-2.156-2.419 0-1.333.955-2.418 2.156-2.418 1.21 0 2.175 1.094 2.156 2.418 0 1.334-.955 2.419-2.156 2.419zm7.974 0c-1.183 0-2.156-1.085-2.156-2.419 0-1.333.955-2.418 2.156-2.418 1.21 0 2.175 1.094 2.156 2.418 0 1.334-.946 2.419-2.156 2.419z" />
                    </svg>
                    Discord
                  </button>
                  <button
                    onClick={() => signIn("google")}
                    className="inline-flex items-center px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-lg shadow-sm hover:bg-gray-50 transition"
                  >
                    <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24">
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                    </svg>
                    Google
                  </button>
                </>
              ) : (
                <div className="flex items-center gap-3">
                  <span className="text-sm text-gray-600">
                    {session.user?.name || session.user?.email}
                  </span>
                  <button
                    onClick={() => signOut()}
                    className="px-4 py-2 bg-gray-200 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-300 transition"
                  >
                    Logout
                  </button>
                </div>
              )}
              <button
                onClick={() => setShowDebug(!showDebug)}
                className="text-xs text-gray-400 hover:text-gray-600"
                title="Toggle debug info"
              >
                🐛
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Debug Panel */}
      {showDebug && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-4">
          <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-900">
            <h3 className="font-bold mb-2 text-sm">Debug: Session & User Info</h3>
            <pre className="text-xs overflow-x-auto bg-yellow-100 p-2 rounded">
              {JSON.stringify({ session, role, groups }, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {/* Main Navigation Tabs */}
      <div className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <nav className="flex space-x-1 overflow-x-auto" aria-label="Main Tabs">
            {mainTabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-4 px-4 border-b-2 font-medium text-sm whitespace-nowrap transition-colors ${
                  activeTab === tab.id
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                <span className="mr-2">{tab.icon}</span>
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <main className="flex-1">
        <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
          {activeTab === 'benchmark' && (
            <HE300Content />
          )}

          {activeTab === 'audit' && (
            <div className="bg-white rounded-lg shadow-sm p-6">
              <AuditLogs />
            </div>
          )}

          {activeTab === 'admin' && (
            <div className="bg-white rounded-lg shadow-sm p-6">
              <AdminTab />
            </div>
          )}

          {activeTab === 'wise' && (
            <div className="bg-white rounded-lg shadow-sm p-6">
              <WiseAuthorityTab />
            </div>
          )}

          {activeTab === 'discord' && (
            <div className="bg-white rounded-lg shadow-sm p-6">
              <DiscordTab />
            </div>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <p className="text-center text-sm text-gray-500">
            <a href="https://ciris.ai" className="hover:text-indigo-600" target="_blank" rel="noopener noreferrer">
              CIRIS.AI
            </a>
            {' '}| EthicsEngine Enterprise | HE-300 Hendrycks Ethics Benchmark
          </p>
        </div>
      </footer>
    </div>
  );
}
