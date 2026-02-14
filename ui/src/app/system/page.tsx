"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import { apiFetch } from "../../lib/api";
import RoleGuard from "../../components/RoleGuard";
import Toast, { type ToastState } from "../../components/Toast";

interface HealthData {
  status: string;
  version?: string;
  uptime?: number;
  postgres?: string;
  redis?: string;
  [key: string]: unknown;
}

interface LogEntry {
  ts: string;
  level: string;
  logger: string;
  message: string;
}

export default function SystemPage() {
  return (
    <RoleGuard allowed={["admin"]}>
      <SystemContent />
    </RoleGuard>
  );
}

function SystemContent() {
  const { data: session } = useSession();
  const token = session?.user?.apiToken;

  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clearingCache, setClearingCache] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const data = await apiFetch<HealthData>("/api/v1/health");
      setHealth(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load health");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  const clearCache = async () => {
    setClearingCache(true);
    try {
      await apiFetch("/api/v1/scores");
      setToast({ type: "success", message: "Cache refresh requested." });
    } catch {
      setToast({ type: "error", message: "Failed to clear cache." });
    } finally {
      setClearingCache(false);
    }
  };

  const statusDot = (status: string | undefined) => {
    const ok = status === "ok" || status === "connected" || status === "healthy";
    return (
      <span
        className={`inline-block w-2.5 h-2.5 rounded-full mr-2 ${
          ok ? "bg-green-500" : "bg-red-500"
        }`}
      />
    );
  };

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading system health...</div>;
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">System Health</h2>

      {/* Health Card */}
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center gap-4 mb-4">
          {statusDot(health?.status as string)}
          <span className="text-lg font-semibold capitalize">{health?.status || "unknown"}</span>
          {health?.version && (
            <span className="text-sm text-gray-500 bg-gray-100 px-2 py-1 rounded">
              v{health.version}
            </span>
          )}
        </div>
        {health?.uptime != null && (
          <p className="text-sm text-gray-500">
            Uptime: {Math.floor(health.uptime / 3600)}h {Math.floor((health.uptime % 3600) / 60)}m
          </p>
        )}
      </div>

      {/* Connected Services */}
      <div className="bg-white shadow rounded-lg p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Connected Services</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="border rounded p-4">
            <div className="flex items-center">
              {statusDot(health?.postgres as string || (health?.status === "ok" ? "ok" : "unknown"))}
              <span className="font-medium">PostgreSQL</span>
            </div>
            <p className="text-sm text-gray-500 mt-1">
              {health?.postgres || (health?.status === "ok" ? "connected" : "unknown")}
            </p>
          </div>
          <div className="border rounded p-4">
            <div className="flex items-center">
              {statusDot(health?.redis as string || (health?.status === "ok" ? "ok" : "unknown"))}
              <span className="font-medium">Redis</span>
            </div>
            <p className="text-sm text-gray-500 mt-1">
              {health?.redis || (health?.status === "ok" ? "connected" : "unknown")}
            </p>
          </div>
          <div className="border rounded p-4">
            <div className="flex items-center">
              {statusDot("ok")}
              <span className="font-medium">CIRISNode API</span>
            </div>
            <p className="text-sm text-gray-500 mt-1">reachable</p>
          </div>
        </div>
      </div>

      {/* Configuration Summary */}
      <div className="bg-white shadow rounded-lg p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Configuration</h3>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
          {Object.entries(health || {})
            .filter(([k]) => !["status", "version", "uptime", "postgres", "redis"].includes(k))
            .map(([key, value]) => (
              <div key={key} className="flex justify-between border-b border-gray-100 py-1">
                <dt className="text-sm font-medium text-gray-500">{key}</dt>
                <dd className="text-sm font-mono text-gray-900">
                  {typeof value === "object" ? JSON.stringify(value) : String(value)}
                </dd>
              </div>
            ))}
        </dl>
      </div>

      {/* Cache Management */}
      <div className="bg-white shadow rounded-lg p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Cache Management</h3>
        <button
          onClick={clearCache}
          disabled={clearingCache}
          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {clearingCache ? "Clearing..." : "Clear Scores Cache"}
        </button>
        <p className="text-sm text-gray-500 mt-2">
          Removes cached frontier scores and embed data. Fresh data will be loaded on next request.
        </p>
      </div>

      {/* Logs Viewer */}
      <LogViewer />

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}

const LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"] as const;

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "text-gray-500",
  INFO: "text-blue-600",
  WARNING: "text-yellow-600",
  ERROR: "text-red-600",
  CRITICAL: "text-red-800 font-bold",
};

function LogViewer() {
  const { data: session } = useSession();
  const token = session?.user?.apiToken;

  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [level, setLevel] = useState<string>("ALL");
  const [pattern, setPattern] = useState("");
  const [limit, setLimit] = useState(200);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loadingLogs, setLoadingLogs] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const [stickToBottom, setStickToBottom] = useState(true);

  const fetchLogs = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      if (level !== "ALL") params.set("level", level);
      if (pattern.trim()) params.set("pattern", pattern.trim());
      const data = await apiFetch<{ logs: LogEntry[]; total: number }>(
        `/api/v1/admin/logs?${params}`,
        { token }
      );
      setLogs(data.logs || []);
      setTotal(data.total || 0);
    } catch {
      // silently fail on refresh
    } finally {
      setLoadingLogs(false);
    }
  }, [level, pattern, limit, token]);

  useEffect(() => {
    setLoadingLogs(true);
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchLogs]);

  // Scroll to bottom when new logs arrive
  useEffect(() => {
    if (stickToBottom && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, stickToBottom]);

  const handleScroll = () => {
    const el = logContainerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setStickToBottom(atBottom);
  };

  const formatTime = (ts: string) => {
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return ts;
    }
  };

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">Application Logs</h3>
        <span className="text-sm text-gray-500">{total} entries</span>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <select
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          className="text-sm border border-gray-300 rounded px-2 py-1.5 bg-white"
        >
          {LEVELS.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>

        <input
          type="text"
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          placeholder="Filter pattern..."
          className="text-sm border border-gray-300 rounded px-3 py-1.5 w-48"
        />

        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="text-sm border border-gray-300 rounded px-2 py-1.5 bg-white"
        >
          <option value={50}>50</option>
          <option value={200}>200</option>
          <option value={500}>500</option>
          <option value={1000}>1000</option>
        </select>

        <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer ml-auto">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
            className="rounded"
          />
          Auto-refresh (5s)
        </label>

        <button
          onClick={fetchLogs}
          className="text-sm px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Log Output */}
      <div
        ref={logContainerRef}
        onScroll={handleScroll}
        className="bg-gray-900 text-gray-100 rounded-lg p-4 font-mono text-xs leading-relaxed overflow-auto"
        style={{ maxHeight: "500px", minHeight: "200px" }}
      >
        {loadingLogs ? (
          <div className="text-gray-500 text-center py-8">Loading logs...</div>
        ) : logs.length === 0 ? (
          <div className="text-gray-500 text-center py-8">No logs matching filters</div>
        ) : (
          logs.map((log, i) => (
            <div key={`${log.ts}-${i}`} className="hover:bg-gray-800 px-1 py-0.5 rounded">
              <span className="text-gray-500">{formatTime(log.ts)}</span>{" "}
              <span className={LEVEL_COLORS[log.level] || "text-gray-300"}>
                {log.level.padEnd(7)}
              </span>{" "}
              <span className="text-gray-400">{log.logger.split(".").pop()}</span>{" "}
              <span className="text-gray-100 break-all">{log.message}</span>
            </div>
          ))
        )}
      </div>

      {!stickToBottom && (
        <button
          onClick={() => {
            setStickToBottom(true);
            if (logContainerRef.current) {
              logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
            }
          }}
          className="mt-2 text-xs text-indigo-600 hover:text-indigo-800"
        >
          Scroll to bottom
        </button>
      )}
    </div>
  );
}
