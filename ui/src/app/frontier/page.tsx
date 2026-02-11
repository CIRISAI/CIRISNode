"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import { apiFetch, apiUrl } from "../../lib/api";
import RoleGuard from "../../components/RoleGuard";

interface FrontierKey {
  provider: string;
  key_preview: string;
  key_length: number;
}

interface FrontierModel {
  model_id: string;
  display_name: string;
  provider: string;
  api_base_url: string;
  default_model_name: string | null;
}

const PROVIDER_DEFAULTS: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com/v1",
  google: "https://generativelanguage.googleapis.com/v1beta",
  groq: "https://api.groq.com/openai/v1",
  grok: "https://api.x.ai/v1",
  openrouter: "https://openrouter.ai/api/v1",
};

interface SweepModel {
  model_id: string;
  display_name: string;
  status: string;
  accuracy: number | null;
  error: string | null;
}

interface SweepProgress {
  sweep_id: string;
  total: number;
  completed: number;
  failed: number;
  pending: number;
  running: number;
  control_status: string;
  models: SweepModel[];
}

interface RecentSweep {
  sweep_id: string;
  total: number;
  completed: number;
  failed: number;
  started_at: string | null;
}

export default function FrontierPage() {
  return (
    <RoleGuard allowed={["admin"]}>
      <FrontierContent />
    </RoleGuard>
  );
}

function FrontierContent() {
  const { data: session } = useSession();
  const token = session?.user?.apiToken;
  const [frontierKeys, setFrontierKeys] = useState<FrontierKey[]>([]);
  const [models, setModels] = useState<FrontierModel[]>([]);
  const [sweeps, setSweeps] = useState<RecentSweep[]>([]);
  const [activeSweep, setActiveSweep] = useState<SweepProgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add model form
  const [showAddForm, setShowAddForm] = useState(false);
  const [newModel, setNewModel] = useState({
    model_id: "",
    display_name: "",
    provider: "",
    api_base_url: "https://api.openai.com/v1",
    default_model_name: "",
  });

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const [keysRes, modelsRes, sweepsRes] = await Promise.all([
        apiFetch<FrontierKey[]>("/api/v1/admin/frontier-keys", { token }),
        apiFetch<FrontierModel[]>("/api/v1/admin/frontier-models", { token }),
        apiFetch<RecentSweep[]>("/api/v1/admin/frontier-sweeps", { token }),
      ]);
      setFrontierKeys(Array.isArray(keysRes) ? keysRes : []);
      setModels(Array.isArray(modelsRes) ? modelsRes : []);
      setSweeps(Array.isArray(sweepsRes) ? sweepsRes : []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // SSE stream for active sweep
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!activeSweep || !token) return;
    const done = activeSweep.control_status === "finished" ||
      (activeSweep.pending === 0 && activeSweep.running === 0);
    if (done) return;

    const controller = new AbortController();
    abortRef.current = controller;

    const streamUrl = apiUrl(`/api/v1/admin/frontier-sweep/${activeSweep.sweep_id}/stream`);
    fetch(streamUrl, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    }).then(async (res) => {
      if (!res.ok || !res.body) return;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const progress: SweepProgress = JSON.parse(line.slice(6));
              setActiveSweep(progress);
              if (progress.pending === 0 && progress.running === 0) {
                fetchData();
              }
            } catch { /* ignore parse errors */ }
          }
        }
      }
    }).catch(() => { /* aborted or network error */ });

    return () => controller.abort();
  }, [activeSweep?.sweep_id, activeSweep?.control_status, token, fetchData]);

  const sweepControl = async (action: "pause" | "resume" | "cancel") => {
    if (!activeSweep) return;
    try {
      await apiFetch(`/api/v1/admin/frontier-sweep/${activeSweep.sweep_id}/${action}`, {
        method: "POST", token,
      });
      // Fetch fresh state
      const progress = await apiFetch<SweepProgress>(
        `/api/v1/admin/frontier-sweep/${activeSweep.sweep_id}`, { token }
      );
      setActiveSweep(progress);
      if (action === "cancel") fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : `Failed to ${action} sweep`);
    }
  };

  const addModel = async () => {
    try {
      await apiFetch("/api/v1/admin/frontier-models", {
        method: "POST",
        body: JSON.stringify(newModel),
        token,
      });
      setShowAddForm(false);
      setNewModel({ model_id: "", display_name: "", provider: "", api_base_url: "https://api.openai.com/v1", default_model_name: "" });
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to add model");
    }
  };

  const deleteModel = async (modelId: string) => {
    if (!confirm(`Delete model ${modelId}?`)) return;
    try {
      await apiFetch(`/api/v1/admin/frontier-models/${modelId}`, { method: "DELETE", token });
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete model");
    }
  };

  const launchSweep = async (modelIds?: string[]) => {
    const label = modelIds ? modelIds.join(", ") : "all registered models";
    if (!confirm(`Launch frontier sweep for ${label}? This runs 300 scenarios per model.`)) return;
    try {
      const body: Record<string, unknown> = { concurrency: 50 };
      if (modelIds) body.model_ids = modelIds;
      const res = await apiFetch<{ sweep_id: string }>("/api/v1/admin/frontier-sweep", {
        method: "POST",
        body: JSON.stringify(body),
        token,
      });
      const progress = await apiFetch<SweepProgress>(
        `/api/v1/admin/frontier-sweep/${res.sweep_id}`, { token }
      );
      setActiveSweep(progress);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to launch sweep");
    }
  };

  const viewSweep = async (sweepId: string) => {
    try {
      const progress = await apiFetch<SweepProgress>(
        `/api/v1/admin/frontier-sweep/${sweepId}`, { token }
      );
      setActiveSweep(progress);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to load sweep");
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

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading frontier data...</div>;
  }

  if (error) {
    return <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">{error}</div>;
  }

  return (
    <div className="space-y-8">
      {/* Configured API Keys */}
      {frontierKeys.length > 0 && (
        <section>
          <h2 className="text-xl font-bold text-gray-900 mb-4">Configured API Keys</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {frontierKeys.map((k) => (
              <div
                key={k.provider}
                className="bg-white shadow rounded-lg px-4 py-3 flex items-center gap-3"
              >
                <span className="text-green-500 text-lg">&#10003;</span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-gray-900 capitalize">{k.provider}</div>
                  <div className="text-xs text-gray-500 font-mono truncate">{k.key_preview}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Model Registry */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900">Frontier Model Registry</h2>
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="px-3 py-1.5 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 transition-colors"
          >
            {showAddForm ? "Cancel" : "Add Model"}
          </button>
        </div>

        {showAddForm && (
          <div className="bg-white shadow rounded-lg p-4 mb-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {(["model_id", "display_name"] as const).map((field) => (
                <div key={field}>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {field.replace(/_/g, " ")}
                  </label>
                  <input
                    type="text"
                    value={newModel[field]}
                    onChange={(e) => setNewModel({ ...newModel, [field]: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </div>
              ))}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">provider</label>
                <select
                  value={newModel.provider}
                  onChange={(e) => {
                    const provider = e.target.value;
                    const baseUrl = PROVIDER_DEFAULTS[provider] || newModel.api_base_url;
                    setNewModel({ ...newModel, provider, api_base_url: baseUrl });
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500 bg-white"
                >
                  <option value="">Select provider...</option>
                  {frontierKeys.map((k) => (
                    <option key={k.provider} value={k.provider}>
                      {k.provider}
                    </option>
                  ))}
                </select>
              </div>
              {(["api_base_url", "default_model_name"] as const).map((field) => (
                <div key={field}>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {field.replace(/_/g, " ")}
                  </label>
                  <input
                    type="text"
                    value={newModel[field]}
                    onChange={(e) => setNewModel({ ...newModel, [field]: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </div>
              ))}
            </div>
            <button
              onClick={addModel}
              className="mt-4 px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 transition-colors"
            >
              Register Model
            </button>
          </div>
        )}

        {models.length === 0 ? (
          <p className="text-gray-500">No models registered. Add one to get started.</p>
        ) : (
          <div className="bg-white shadow rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Display Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Provider</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">API Base URL</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {models.map((m) => (
                  <tr key={m.model_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-mono">{m.model_id}</td>
                    <td className="px-4 py-3 text-sm">{m.display_name}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{m.provider}</td>
                    <td className="px-4 py-3 text-sm text-gray-500 truncate max-w-xs">{m.api_base_url}</td>
                    <td className="px-4 py-3 text-sm space-x-3">
                      <button
                        onClick={() => launchSweep([m.model_id])}
                        className="text-indigo-600 hover:text-indigo-800 text-sm"
                      >
                        Run
                      </button>
                      <button
                        onClick={() => deleteModel(m.model_id)}
                        className="text-red-600 hover:text-red-800 text-sm"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Sweep Control */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900">Sweep Control</h2>
          <button
            onClick={() => launchSweep()}
            disabled={models.length === 0}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            Launch Sweep
          </button>
        </div>

        {/* Active Sweep Progress */}
        {activeSweep && (
          <div className="bg-white shadow rounded-lg p-6 mb-6">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <h3 className="text-lg font-semibold">Sweep: {activeSweep.sweep_id}</h3>
                {statusBadge(activeSweep.control_status)}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-500 mr-2">
                  {activeSweep.completed + activeSweep.failed} / {activeSweep.total} models
                </span>
                {activeSweep.control_status === "running" && (
                  <button
                    onClick={() => sweepControl("pause")}
                    className="px-3 py-1 bg-yellow-500 text-white text-xs rounded hover:bg-yellow-600 transition-colors"
                  >
                    Pause
                  </button>
                )}
                {activeSweep.control_status === "paused" && (
                  <button
                    onClick={() => sweepControl("resume")}
                    className="px-3 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700 transition-colors"
                  >
                    Resume
                  </button>
                )}
                {(activeSweep.control_status === "running" || activeSweep.control_status === "paused") && (
                  <button
                    onClick={() => sweepControl("cancel")}
                    className="px-3 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700 transition-colors"
                  >
                    Cancel
                  </button>
                )}
                {(activeSweep.control_status === "finished" || activeSweep.control_status === "cancelled") && (
                  <button
                    onClick={() => setActiveSweep(null)}
                    className="px-3 py-1 bg-gray-500 text-white text-xs rounded hover:bg-gray-600 transition-colors"
                  >
                    Dismiss
                  </button>
                )}
              </div>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-3 mb-4">
              <div
                className="bg-indigo-600 h-3 rounded-full transition-all"
                style={{
                  width: `${((activeSweep.completed + activeSweep.failed) / Math.max(activeSweep.total, 1)) * 100}%`,
                }}
              />
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                    <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Accuracy</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {activeSweep.models.map((m) => (
                    <tr key={m.model_id} className={m.status === "running" ? "bg-blue-50" : ""}>
                      <td className="px-4 py-2 text-sm">{m.display_name || m.model_id}</td>
                      <td className="px-4 py-2 text-sm">{statusBadge(m.status)}</td>
                      <td className="px-4 py-2 text-sm text-right font-mono">
                        {m.accuracy != null ? `${(m.accuracy * 100).toFixed(1)}%` : "-"}
                      </td>
                      <td className="px-4 py-2 text-sm text-red-600 truncate max-w-xs">{m.error || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Recent Sweeps */}
        <h3 className="text-lg font-semibold text-gray-900 mb-3">Recent Sweeps</h3>
        {sweeps.length === 0 ? (
          <p className="text-gray-500">No sweeps run yet.</p>
        ) : (
          <div className="bg-white shadow rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Sweep ID</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Models</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Completed</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Failed</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Started</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {sweeps.map((s) => (
                  <tr key={s.sweep_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-mono">{s.sweep_id}</td>
                    <td className="px-4 py-3 text-sm text-right">{s.total}</td>
                    <td className="px-4 py-3 text-sm text-right text-green-600">{s.completed}</td>
                    <td className="px-4 py-3 text-sm text-right text-red-600">{s.failed}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {s.started_at ? new Date(s.started_at).toLocaleString() : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <button
                        onClick={() => viewSweep(s.sweep_id)}
                        className="text-indigo-600 hover:text-indigo-800"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
