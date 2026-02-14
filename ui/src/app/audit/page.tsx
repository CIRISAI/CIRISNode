"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { apiFetch } from "../../lib/api";

interface AuditLog {
  id: string;
  timestamp: string;
  actor: string;
  event_type: string;
  payload_sha256: string;
  details: unknown;
  archived?: boolean;
}

export default function AuditPage() {
  const { data: session } = useSession();
  const token = session?.user?.apiToken;

  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Filters
  const [actorFilter, setActorFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ logs: AuditLog[] }>("/api/v1/audit/logs", { token });
      setLogs(data.logs || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit logs");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const exportJson = () => {
    const filtered = getFiltered();
    const blob = new Blob([JSON.stringify(filtered, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getFiltered = () =>
    logs
      .filter((l) => showArchived || !l.archived)
      .filter((l) => !actorFilter || l.actor.toLowerCase().includes(actorFilter.toLowerCase()))
      .filter((l) => !typeFilter || l.event_type.toLowerCase().includes(typeFilter.toLowerCase()));

  const filtered = getFiltered();

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading audit logs...</div>;
  }

  if (error) {
    return <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">{error}</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-900">Audit Log</h2>
        <button
          onClick={exportJson}
          className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded hover:bg-gray-800 transition-colors"
        >
          Export JSON
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white shadow rounded-lg p-4">
        <div className="flex items-center gap-4 flex-wrap">
          <input
            type="text"
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
            placeholder="Filter by actor..."
            className="px-3 py-2 border border-gray-300 rounded text-sm w-48"
          />
          <input
            type="text"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            placeholder="Filter by event type..."
            className="px-3 py-2 border border-gray-300 rounded text-sm w-48"
          />
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
            />
            Show archived
          </label>
          <button
            onClick={fetchLogs}
            className="text-sm text-indigo-600 hover:text-indigo-800 ml-auto"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <p className="text-gray-500">No audit logs found.</p>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actor</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Event Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Payload SHA256</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {filtered.map((log) => (
                <>
                  <tr
                    key={log.id}
                    className={`hover:bg-gray-50 cursor-pointer ${log.archived ? "opacity-50" : ""}`}
                    onClick={() => setExpandedId(expandedId === log.id ? null : log.id)}
                  >
                    <td className="px-4 py-3 text-sm font-mono text-gray-700">{log.id}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {new Date(log.timestamp).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm">{log.actor}</td>
                    <td className="px-4 py-3 text-sm">
                      <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700">
                        {log.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm font-mono text-gray-500 truncate max-w-[120px]">
                      {log.payload_sha256}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-400">
                      {expandedId === log.id ? "collapse" : "expand"}
                    </td>
                  </tr>
                  {expandedId === log.id && (
                    <tr key={`${log.id}-detail`}>
                      <td colSpan={6} className="px-4 py-3 bg-gray-50">
                        <pre className="text-xs font-mono bg-white p-3 rounded border overflow-x-auto max-h-64">
                          {JSON.stringify(
                            typeof log.details === "string"
                              ? JSON.parse(log.details)
                              : log.details,
                            null,
                            2
                          )}
                        </pre>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
