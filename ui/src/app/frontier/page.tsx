"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "../../lib/api";
import RoleGuard from "../../components/RoleGuard";

interface FrontierModel {
  model_id: string;
  display_name: string;
  provider: string;
  api_base_url: string;
  default_model_name: string | null;
}

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
    try {
      const [modelsRes, sweepsRes] = await Promise.all([
        apiFetch<{ models: FrontierModel[] }>("/api/v1/admin/frontier-models"),
        apiFetch<{ sweeps: RecentSweep[] }>("/api/v1/admin/frontier-sweeps"),
      ]);
      setModels(modelsRes.models || []);
      setSweeps(sweepsRes.sweeps || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll active sweep
  useEffect(() => {
    if (!activeSweep) return;
    const done = activeSweep.pending === 0 && activeSweep.running === 0;
    if (done) return;

    const interval = setInterval(async () => {
      try {
        const progress = await apiFetch<SweepProgress>(
          `/api/v1/admin/frontier-sweep/${activeSweep.sweep_id}`
        );
        setActiveSweep(progress);
        if (progress.pending === 0 && progress.running === 0) {
          fetchData();
        }
      } catch {
        // ignore polling errors
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [activeSweep, fetchData]);

  const addModel = async () => {
    try {
      await apiFetch("/api/v1/admin/frontier-models", {
        method: "POST",
        body: JSON.stringify(newModel),
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
      await apiFetch(`/api/v1/admin/frontier-models/${modelId}`, { method: "DELETE" });
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete model");
    }
  };

  const launchSweep = async () => {
    if (!confirm("Launch frontier sweep across all registered models? This runs 300 scenarios per model.")) return;
    try {
      const res = await apiFetch<{ sweep_id: string }>("/api/v1/admin/frontier-sweep", {
        method: "POST",
        body: JSON.stringify({ concurrency: 50 }),
      });
      const progress = await apiFetch<SweepProgress>(
        `/api/v1/admin/frontier-sweep/${res.sweep_id}`
      );
      setActiveSweep(progress);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to launch sweep");
    }
  };

  const viewSweep = async (sweepId: string) => {
    try {
      const progress = await apiFetch<SweepProgress>(
        `/api/v1/admin/frontier-sweep/${sweepId}`
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
              {(["model_id", "display_name", "provider", "api_base_url", "default_model_name"] as const).map((field) => (
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
                    <td className="px-4 py-3 text-sm">
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
            onClick={launchSweep}
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
              <h3 className="text-lg font-semibold">Sweep: {activeSweep.sweep_id}</h3>
              <span className="text-sm text-gray-500">
                {activeSweep.completed + activeSweep.failed} / {activeSweep.total} models
              </span>
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
                    <tr key={m.model_id}>
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
