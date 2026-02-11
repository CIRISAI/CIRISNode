"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSession } from "next-auth/react";
import { apiFetch, apiUrl } from "../../lib/api";
import RoleGuard from "../../components/RoleGuard";
import ConfirmModal from "../../components/ConfirmModal";
import Toast, { type ToastState } from "../../components/Toast";

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
  cost_per_1m_input: number | null;
  cost_per_1m_output: number | null;
  supports_reasoning: boolean;
  reasoning_effort: string | null;
}

const PROVIDER_DEFAULTS: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com/v1",
  google: "https://generativelanguage.googleapis.com/v1beta",
  groq: "https://api.groq.com/openai/v1",
  grok: "https://api.x.ai/v1",
  openrouter: "https://openrouter.ai/api/v1",
  together: "https://api.together.xyz/v1",
};

// Known model pricing (USD per 1M tokens) for auto-fill
const MODEL_PRICING: Record<string, { input: number; output: number; reasoning?: boolean }> = {
  "gpt-4o": { input: 2.50, output: 10.00 },
  "gpt-4o-mini": { input: 0.15, output: 0.60 },
  "gpt-4.5-preview": { input: 75.00, output: 150.00 },
  "o3": { input: 10.00, output: 40.00, reasoning: true },
  "o3-mini": { input: 1.10, output: 4.40, reasoning: true },
  "o4-mini": { input: 1.10, output: 4.40, reasoning: true },
  "claude-4-opus": { input: 15.00, output: 75.00 },
  "claude-4-sonnet": { input: 3.00, output: 15.00 },
  "claude-3.5-haiku": { input: 0.80, output: 4.00 },
  "gemini-2.5-pro": { input: 1.25, output: 10.00 },
  "gemini-2.5-flash": { input: 0.15, output: 0.60 },
  "gemini-2.0-pro": { input: 1.25, output: 5.00 },
  "gemini-2.0-flash": { input: 0.10, output: 0.40 },
  "grok-3": { input: 3.00, output: 15.00 },
  "grok-3-mini": { input: 0.30, output: 0.50 },
  "llama-4-maverick": { input: 0.20, output: 0.60 },
  "llama-4-scout": { input: 0.15, output: 0.40 },
  "deepseek-r1": { input: 0.55, output: 2.19, reasoning: true },
  "mistral-large": { input: 2.00, output: 6.00 },
  "command-r-plus": { input: 2.50, output: 10.00 },
};

// Cost estimation constants for HE-300
const AVG_INPUT_TOKENS_PER_SCENARIO = 150;
const AVG_OUTPUT_TOKENS_PER_SCENARIO = 100;
const SCENARIOS_PER_SWEEP = 300;

function estimateSweepCost(costInput: number | null, costOutput: number | null): number | null {
  if (costInput == null || costOutput == null) return null;
  const inputTotal = (SCENARIOS_PER_SWEEP * AVG_INPUT_TOKENS_PER_SCENARIO) / 1_000_000;
  const outputTotal = (SCENARIOS_PER_SWEEP * AVG_OUTPUT_TOKENS_PER_SCENARIO) / 1_000_000;
  return costInput * inputTotal + costOutput * outputTotal;
}

interface SweepModel {
  model_id: string;
  display_name: string;
  status: string;
  accuracy: number | null;
  total_scenarios: number | null;
  scenarios_completed: number | null;
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
  concurrency: number;
  global_concurrency: number;
  provider_concurrency: number;
  models: SweepModel[];
}

interface RecentSweep {
  sweep_id: string;
  total: number;
  completed: number;
  failed: number;
  started_at: string | null;
}

interface LogEntry {
  ts: string;
  level: string;
  logger: string;
  message: string;
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

  // Modal + toast state
  const [confirmState, setConfirmState] = useState<{
    title: string; message: string; variant?: "danger" | "default"; onConfirm: () => void;
  } | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  // Add model form
  const [showAddForm, setShowAddForm] = useState(false);
  const [newModel, setNewModel] = useState({
    model_id: "",
    display_name: "",
    provider: "",
    api_base_url: "https://api.openai.com/v1",
    default_model_name: "",
    cost_per_1m_input: "",
    cost_per_1m_output: "",
    supports_reasoning: false,
    reasoning_effort: "",
  });

  // Logs state
  const [showLogs, setShowLogs] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logLevel, setLogLevel] = useState("");
  const [logPattern, setLogPattern] = useState("");
  const [logsLoading, setLogsLoading] = useState(false);
  const logIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  // Log fetching
  const fetchLogs = useCallback(async () => {
    if (!token) return;
    setLogsLoading(true);
    try {
      const params = new URLSearchParams({ limit: "500" });
      if (logLevel) params.set("level", logLevel);
      if (logPattern) params.set("pattern", logPattern);
      const res = await apiFetch<{ logs: LogEntry[]; total: number }>(
        `/api/v1/admin/logs?${params.toString()}`, { token }
      );
      setLogs(res.logs || []);
    } catch {
      /* ignore log fetch errors */
    } finally {
      setLogsLoading(false);
    }
  }, [token, logLevel, logPattern]);

  useEffect(() => {
    if (!showLogs) {
      if (logIntervalRef.current) clearInterval(logIntervalRef.current);
      return;
    }
    fetchLogs();
    logIntervalRef.current = setInterval(fetchLogs, 5000);
    return () => {
      if (logIntervalRef.current) clearInterval(logIntervalRef.current);
    };
  }, [showLogs, fetchLogs]);

  const sweepControl = async (action: "pause" | "resume" | "cancel") => {
    if (!activeSweep) return;
    try {
      await apiFetch(`/api/v1/admin/frontier-sweep/${activeSweep.sweep_id}/${action}`, {
        method: "POST", token,
      });
      const progress = await apiFetch<SweepProgress>(
        `/api/v1/admin/frontier-sweep/${activeSweep.sweep_id}`, { token }
      );
      setActiveSweep(progress);
      if (action === "cancel") fetchData();
    } catch (err) {
      setToast({ type: "error", message: err instanceof Error ? err.message : `Failed to ${action} sweep` });
    }
  };

  const addModel = async () => {
    try {
      const body: Record<string, unknown> = {
        model_id: newModel.model_id,
        display_name: newModel.display_name,
        provider: newModel.provider,
        api_base_url: newModel.api_base_url,
        default_model_name: newModel.default_model_name || null,
        cost_per_1m_input: newModel.cost_per_1m_input ? parseFloat(newModel.cost_per_1m_input) : null,
        cost_per_1m_output: newModel.cost_per_1m_output ? parseFloat(newModel.cost_per_1m_output) : null,
        supports_reasoning: newModel.supports_reasoning,
        reasoning_effort: newModel.reasoning_effort || null,
      };
      await apiFetch("/api/v1/admin/frontier-models", {
        method: "POST",
        body: JSON.stringify(body),
        token,
      });
      setShowAddForm(false);
      setNewModel({
        model_id: "", display_name: "", provider: "",
        api_base_url: "https://api.openai.com/v1", default_model_name: "",
        cost_per_1m_input: "", cost_per_1m_output: "",
        supports_reasoning: false, reasoning_effort: "",
      });
      fetchData();
    } catch (err) {
      setToast({ type: "error", message: err instanceof Error ? err.message : "Failed to add model" });
    }
  };

  const deleteModel = (modelId: string) => {
    setConfirmState({
      title: "Delete Model",
      message: `Delete model ${modelId}?`,
      variant: "danger",
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await apiFetch(`/api/v1/admin/frontier-models/${encodeURIComponent(modelId)}`, { method: "DELETE", token });
          fetchData();
        } catch (err) {
          setToast({ type: "error", message: err instanceof Error ? err.message : "Failed to delete model" });
        }
      },
    });
  };

  const launchSweep = (modelIds?: string[]) => {
    const label = modelIds ? modelIds.join(", ") : "all registered models";
    const selectedModels = modelIds
      ? models.filter(m => modelIds.includes(m.model_id))
      : models;
    const totalCost = selectedModels.reduce((sum, m) => {
      const est = estimateSweepCost(m.cost_per_1m_input, m.cost_per_1m_output);
      return sum + (est || 0);
    }, 0);
    const semanticCost = selectedModels.length * 0.01;
    const grandTotal = totalCost + semanticCost;
    const costStr = grandTotal > 0 ? `\nEstimated cost: $${grandTotal.toFixed(4)} (incl. semantic eval)` : "";
    setConfirmState({
      title: "Launch Frontier Sweep",
      message: `Launch frontier sweep for ${label}? This runs 300 scenarios per model with semantic evaluation.${costStr}`,
      onConfirm: async () => {
        setConfirmState(null);
        try {
          const body: Record<string, unknown> = {
            concurrency: 50,
            semantic_evaluation: true,
            evaluator_model: "gpt-4o-mini",
            evaluator_provider: "openai",
          };
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
          setToast({ type: "error", message: err instanceof Error ? err.message : "Failed to launch sweep" });
        }
      },
    });
  };

  const viewSweep = async (sweepId: string) => {
    try {
      const progress = await apiFetch<SweepProgress>(
        `/api/v1/admin/frontier-sweep/${sweepId}`, { token }
      );
      setActiveSweep(progress);
    } catch (err) {
      setToast({ type: "error", message: err instanceof Error ? err.message : "Failed to load sweep" });
    }
  };

  const deleteSweep = (sweepId: string) => {
    setConfirmState({
      title: "Delete Sweep",
      message: `Delete sweep ${sweepId} and all its evaluation data? This cannot be undone.`,
      variant: "danger",
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await apiFetch(`/api/v1/admin/frontier-sweep/${sweepId}`, { method: "DELETE", token });
          if (activeSweep?.sweep_id === sweepId) setActiveSweep(null);
          fetchData();
        } catch (err) {
          setToast({ type: "error", message: err instanceof Error ? err.message : "Failed to delete sweep" });
        }
      },
    });
  };

  // Auto-fill pricing when model_id matches known models
  const handleModelIdChange = (value: string) => {
    const pricing = MODEL_PRICING[value];
    setNewModel(prev => ({
      ...prev,
      model_id: value,
      cost_per_1m_input: pricing ? String(pricing.input) : prev.cost_per_1m_input,
      cost_per_1m_output: pricing ? String(pricing.output) : prev.cost_per_1m_output,
      supports_reasoning: pricing?.reasoning ?? prev.supports_reasoning,
      reasoning_effort: pricing?.reasoning ? (prev.reasoning_effort || "medium") : prev.reasoning_effort,
    }));
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

  const logLevelColor = (level: string) => {
    switch (level) {
      case "ERROR": return "text-red-600";
      case "WARNING": return "text-yellow-600";
      case "INFO": return "text-blue-600";
      case "DEBUG": return "text-gray-400";
      default: return "text-gray-600";
    }
  };

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading frontier data...</div>;
  }

  if (error) {
    return <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">{error}</div>;
  }

  // Calculate total sweep cost for all models
  const totalSweepCost = models.reduce((sum, m) => {
    const est = estimateSweepCost(m.cost_per_1m_input, m.cost_per_1m_output);
    return sum + (est || 0);
  }, 0);

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
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">model id</label>
                <input
                  type="text"
                  value={newModel.model_id}
                  onChange={(e) => handleModelIdChange(e.target.value)}
                  placeholder="e.g. gpt-4o, o3-mini"
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
                {MODEL_PRICING[newModel.model_id] && (
                  <p className="text-xs text-green-600 mt-1">Pricing auto-filled from known model</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">display name</label>
                <input
                  type="text"
                  value={newModel.display_name}
                  onChange={(e) => setNewModel({ ...newModel, display_name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
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
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">api base url</label>
                <input
                  type="text"
                  value={newModel.api_base_url}
                  onChange={(e) => setNewModel({ ...newModel, api_base_url: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">default model name</label>
                <input
                  type="text"
                  value={newModel.default_model_name}
                  onChange={(e) => setNewModel({ ...newModel, default_model_name: e.target.value })}
                  placeholder="defaults to model_id"
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">$/1M input</label>
                  <input
                    type="number"
                    step="0.01"
                    value={newModel.cost_per_1m_input}
                    onChange={(e) => setNewModel({ ...newModel, cost_per_1m_input: e.target.value })}
                    placeholder="2.50"
                    className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">$/1M output</label>
                  <input
                    type="number"
                    step="0.01"
                    value={newModel.cost_per_1m_output}
                    onChange={(e) => setNewModel({ ...newModel, cost_per_1m_output: e.target.value })}
                    placeholder="10.00"
                    className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </div>
              </div>
              <div className="flex items-end gap-4">
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={newModel.supports_reasoning}
                    onChange={(e) => setNewModel({
                      ...newModel,
                      supports_reasoning: e.target.checked,
                      reasoning_effort: e.target.checked ? (newModel.reasoning_effort || "medium") : "",
                    })}
                    className="rounded border-gray-300"
                  />
                  Reasoning model
                </label>
                {newModel.supports_reasoning && (
                  <select
                    value={newModel.reasoning_effort}
                    onChange={(e) => setNewModel({ ...newModel, reasoning_effort: e.target.value })}
                    className="px-3 py-2 border border-gray-300 rounded text-sm bg-white focus:ring-indigo-500 focus:border-indigo-500"
                  >
                    <option value="low">Low effort</option>
                    <option value="medium">Medium effort</option>
                    <option value="high">High effort</option>
                  </select>
                )}
              </div>
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
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">$/1M In</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">$/1M Out</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Est. Sweep</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Reasoning</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {models.map((m) => {
                  const sweepCost = estimateSweepCost(m.cost_per_1m_input, m.cost_per_1m_output);
                  return (
                    <tr key={m.model_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-mono">{m.model_id}</td>
                      <td className="px-4 py-3 text-sm">{m.display_name}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">{m.provider}</td>
                      <td className="px-4 py-3 text-sm text-right font-mono text-gray-600">
                        {m.cost_per_1m_input != null ? `$${m.cost_per_1m_input.toFixed(2)}` : "-"}
                      </td>
                      <td className="px-4 py-3 text-sm text-right font-mono text-gray-600">
                        {m.cost_per_1m_output != null ? `$${m.cost_per_1m_output.toFixed(2)}` : "-"}
                      </td>
                      <td className="px-4 py-3 text-sm text-right font-mono text-gray-600">
                        {sweepCost != null ? `$${sweepCost.toFixed(4)}` : "-"}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {m.supports_reasoning ? (
                          <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-purple-100 text-purple-700 font-medium">
                            {m.reasoning_effort || "medium"}
                          </span>
                        ) : (
                          <span className="text-gray-400">-</span>
                        )}
                      </td>
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
                  );
                })}
              </tbody>
              {totalSweepCost > 0 && (
                <tfoot className="bg-gray-50">
                  <tr>
                    <td colSpan={5} className="px-4 py-2 text-sm font-medium text-gray-700 text-right">
                      Full sweep estimate:
                    </td>
                    <td className="px-4 py-2 text-sm text-right font-mono font-semibold text-gray-900">
                      ${totalSweepCost.toFixed(4)}
                    </td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              )}
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
            {/* Concurrency info */}
            <div className="flex items-center gap-4 text-xs text-gray-500 mb-3">
              <span>Scenario concurrency: <strong className="text-gray-700">{activeSweep.concurrency}</strong></span>
              <span>Global model slots: <strong className="text-gray-700">{activeSweep.global_concurrency}</strong></span>
              <span>Per-provider: <strong className="text-gray-700">{activeSweep.provider_concurrency}</strong></span>
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
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase w-40">Progress</th>
                    <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Accuracy</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {activeSweep.models.map((m) => {
                    const pct = m.scenarios_completed != null && m.total_scenarios
                      ? Math.round((m.scenarios_completed / m.total_scenarios) * 100)
                      : null;
                    return (
                      <tr key={m.model_id} className={m.status === "running" ? "bg-blue-50" : ""}>
                        <td className="px-4 py-2 text-sm">{m.display_name || m.model_id}</td>
                        <td className="px-4 py-2 text-sm">{statusBadge(m.status)}</td>
                        <td className="px-4 py-2 text-sm">
                          {m.status === "running" && pct != null ? (
                            <div className="flex items-center gap-2">
                              <div className="flex-1 bg-gray-200 rounded-full h-2">
                                <div
                                  className="bg-blue-500 h-2 rounded-full transition-all"
                                  style={{ width: `${pct}%` }}
                                />
                              </div>
                              <span className="text-xs font-mono text-gray-600 w-12 text-right">
                                {m.scenarios_completed}/{m.total_scenarios}
                              </span>
                            </div>
                          ) : m.status === "completed" ? (
                            <span className="text-xs text-green-600 font-medium">Done</span>
                          ) : m.status === "failed" ? (
                            <span className="text-xs text-red-600 font-medium">Failed</span>
                          ) : m.status === "running" ? (
                            <span className="text-xs text-blue-500">Starting...</span>
                          ) : (
                            <span className="text-xs text-gray-400">Queued</span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-sm text-right font-mono">
                          {m.accuracy != null ? `${(m.accuracy * 100).toFixed(1)}%` : "-"}
                        </td>
                        <td className="px-4 py-2 text-sm text-red-600 truncate max-w-xs">{m.error || ""}</td>
                      </tr>
                    );
                  })}
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
                    <td className="px-4 py-3 text-sm space-x-3">
                      <button
                        onClick={() => viewSweep(s.sweep_id)}
                        className="text-indigo-600 hover:text-indigo-800"
                      >
                        View
                      </button>
                      <button
                        onClick={() => deleteSweep(s.sweep_id)}
                        className="text-red-600 hover:text-red-800"
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

      {/* Node Logs */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900">Node Logs</h2>
          <button
            onClick={() => setShowLogs(!showLogs)}
            className="px-3 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-700 transition-colors"
          >
            {showLogs ? "Hide Logs" : "Show Logs"}
          </button>
        </div>

        {showLogs && (
          <div className="bg-gray-900 rounded-lg shadow overflow-hidden">
            <div className="flex items-center gap-3 px-4 py-2 bg-gray-800 border-b border-gray-700">
              <select
                value={logLevel}
                onChange={(e) => setLogLevel(e.target.value)}
                className="px-2 py-1 bg-gray-700 text-gray-200 text-xs rounded border border-gray-600"
              >
                <option value="">All levels</option>
                <option value="ERROR">ERROR</option>
                <option value="WARNING">WARNING</option>
                <option value="INFO">INFO</option>
                <option value="DEBUG">DEBUG</option>
              </select>
              <input
                type="text"
                value={logPattern}
                onChange={(e) => setLogPattern(e.target.value)}
                placeholder="Filter pattern..."
                className="flex-1 px-2 py-1 bg-gray-700 text-gray-200 text-xs rounded border border-gray-600 placeholder-gray-500"
              />
              <button
                onClick={fetchLogs}
                className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded hover:bg-gray-600"
              >
                {logsLoading ? "..." : "Refresh"}
              </button>
              <span className="text-xs text-gray-500">{logs.length} entries (auto-refresh 5s)</span>
            </div>
            <div className="overflow-auto max-h-96 font-mono text-xs leading-5">
              {logs.length === 0 ? (
                <div className="px-4 py-8 text-gray-500 text-center">
                  {logsLoading ? "Loading logs..." : "No logs matching filter"}
                </div>
              ) : (
                <table className="w-full">
                  <tbody>
                    {logs.map((log, i) => (
                      <tr key={i} className="hover:bg-gray-800">
                        <td className="px-2 py-0.5 text-gray-500 whitespace-nowrap align-top">
                          {new Date(log.ts).toLocaleTimeString()}
                        </td>
                        <td className={`px-2 py-0.5 whitespace-nowrap align-top font-semibold ${logLevelColor(log.level)}`}>
                          {log.level.padEnd(7)}
                        </td>
                        <td className="px-2 py-0.5 text-gray-400 whitespace-nowrap align-top max-w-[120px] truncate">
                          {log.logger}
                        </td>
                        <td className="px-2 py-0.5 text-gray-200 whitespace-pre-wrap break-all">
                          {log.message}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </section>

      <ConfirmModal
        isOpen={!!confirmState}
        title={confirmState?.title ?? ""}
        message={confirmState?.message ?? ""}
        variant={confirmState?.variant}
        onConfirm={() => confirmState?.onConfirm()}
        onCancel={() => setConfirmState(null)}
      />
      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
