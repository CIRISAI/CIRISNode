"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { apiFetch } from "../../lib/api";

interface Evaluation {
  id: string;
  eval_type: string;
  target_model: string;
  provider: string | null;
  accuracy: number | null;
  status: string;
  visibility: string;
  total_scenarios: number;
  categories: Record<string, { correct: number; total: number; accuracy: number }> | null;
  badges: string[];
  created_at: string | null;
  completed_at: string | null;
  agent_name: string | null;
  archived_at: string | null;
}

export default function EvaluationsPage() {
  const { data: session } = useSession();
  const token = session?.user?.apiToken;

  const [evals, setEvals] = useState<Evaluation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Filters
  const [evalType, setEvalType] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [showArchived, setShowArchived] = useState(false);

  // Selection
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [actionLoading, setActionLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (evalType) params.set("eval_type", evalType);
      if (statusFilter) params.set("status", statusFilter);
      if (modelFilter) params.set("model", modelFilter);
      if (showArchived) params.set("include_archived", "true");
      const qs = params.toString();
      const data = await apiFetch<{ evaluations: Evaluation[] }>(
        `/api/v1/evaluations${qs ? `?${qs}` : ""}`,
        token ? { token } : undefined
      );
      setEvals(data.evaluations || []);
      setSelected(new Set());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load evaluations");
    } finally {
      setLoading(false);
    }
  }, [evalType, statusFilter, modelFilter, showArchived, token]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === evals.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(evals.map((ev) => ev.id)));
    }
  };

  const handleBulkAction = async (action: "archive" | "restore") => {
    if (!token || selected.size === 0) return;
    setActionLoading(true);
    try {
      const ids = Array.from(selected);
      await apiFetch(`/api/v1/evaluations/${action}`, {
        method: "POST",
        token,
        body: JSON.stringify({ ids }),
      });
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${action}`);
    } finally {
      setActionLoading(false);
    }
  };

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "bg-gray-100 text-gray-700",
      running: "bg-blue-100 text-blue-700",
      completed: "bg-green-100 text-green-700",
      failed: "bg-red-100 text-red-700",
    };
    return (
      <span className={`text-xs px-2 py-0.5 rounded font-medium ${colors[status] || "bg-gray-100 text-gray-700"}`}>
        {status}
      </span>
    );
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">Evaluations</h2>

      {/* Filter Bar */}
      <div className="bg-white shadow rounded-lg p-4">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
            <select
              value={evalType}
              onChange={(e) => setEvalType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
            >
              <option value="">All</option>
              <option value="frontier">Frontier</option>
              <option value="client">Client</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
            >
              <option value="">All</option>
              <option value="completed">Completed</option>
              <option value="pending">Pending</option>
              <option value="running">Running</option>
              <option value="failed">Failed</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
            <input
              type="text"
              value={modelFilter}
              onChange={(e) => setModelFilter(e.target.value)}
              placeholder="Filter by model..."
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
            />
          </div>
          <div className="flex items-center gap-2 pt-1">
            <input
              type="checkbox"
              id="show-archived"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              className="rounded border-gray-300"
            />
            <label htmlFor="show-archived" className="text-sm text-gray-700">
              Show Archived
            </label>
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Action Bar */}
      {selected.size > 0 && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-3 flex items-center gap-3">
          <span className="text-sm font-medium text-indigo-900">
            {selected.size} selected
          </span>
          <button
            onClick={() => handleBulkAction("archive")}
            disabled={actionLoading}
            className="px-3 py-1.5 bg-amber-600 text-white text-sm rounded hover:bg-amber-700 disabled:opacity-50"
          >
            Archive Selected
          </button>
          {showArchived && (
            <button
              onClick={() => handleBulkAction("restore")}
              disabled={actionLoading}
              className="px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
            >
              Restore Selected
            </button>
          )}
          <button
            onClick={() => setSelected(new Set())}
            className="px-3 py-1.5 text-gray-600 text-sm hover:text-gray-900"
          >
            Clear
          </button>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">{error}</div>
      )}

      {/* Table */}
      {evals.length === 0 ? (
        <p className="text-gray-500">No evaluations found.</p>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-3 text-left">
                  <input
                    type="checkbox"
                    checked={selected.size === evals.length && evals.length > 0}
                    onChange={toggleSelectAll}
                    className="rounded border-gray-300"
                  />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Accuracy</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Visibility</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Scenarios</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {evals.map((ev) => (
                <>
                  <tr
                    key={ev.id}
                    className={`hover:bg-gray-50 cursor-pointer ${ev.archived_at ? "opacity-50" : ""}`}
                    onClick={() => setExpandedId(expandedId === ev.id ? null : ev.id)}
                  >
                    <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(ev.id)}
                        onChange={() => toggleSelect(ev.id)}
                        className="rounded border-gray-300"
                      />
                    </td>
                    <td className="px-4 py-3 text-sm font-mono text-gray-700 truncate max-w-[120px]">{ev.id.slice(0, 8)}</td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`text-xs px-2 py-0.5 rounded ${ev.eval_type === "frontier" ? "bg-purple-100 text-purple-700" : "bg-blue-100 text-blue-700"}`}>
                        {ev.eval_type}
                      </span>
                      {ev.archived_at && (
                        <span className="ml-1 text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-700">
                          archived
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm">{ev.target_model}</td>
                    <td className="px-4 py-3 text-sm text-right font-mono">
                      {ev.accuracy != null ? `${(ev.accuracy * 100).toFixed(1)}%` : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm">{statusBadge(ev.status)}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{ev.visibility}</td>
                    <td className="px-4 py-3 text-sm text-right">{ev.total_scenarios}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {ev.created_at ? new Date(ev.created_at).toLocaleString() : "-"}
                    </td>
                  </tr>
                  {expandedId === ev.id && ev.categories && (
                    <tr key={`${ev.id}-detail`}>
                      <td colSpan={9} className="px-4 py-3 bg-gray-50">
                        <div className="text-sm font-medium text-gray-700 mb-2">Category Breakdown</div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                          {Object.entries(ev.categories).map(([cat, data]) => (
                            <div key={cat} className="bg-white p-2 rounded border">
                              <div className="text-xs text-gray-500 capitalize">{cat}</div>
                              <div className="text-sm font-mono">
                                {(data.accuracy * 100).toFixed(1)}%
                                <span className="text-gray-400 text-xs ml-1">({data.correct}/{data.total})</span>
                              </div>
                            </div>
                          ))}
                        </div>
                        {ev.badges && ev.badges.length > 0 && (
                          <div className="mt-2 flex gap-1">
                            {ev.badges.map((b) => (
                              <span key={b} className="inline-block bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded">{b}</span>
                            ))}
                          </div>
                        )}
                        {ev.archived_at && (
                          <div className="mt-2 text-xs text-amber-600">
                            Archived on {new Date(ev.archived_at).toLocaleString()}
                          </div>
                        )}
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
