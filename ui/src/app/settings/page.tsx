"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { apiFetch } from "../../lib/api";
import RoleGuard from "../../components/RoleGuard";
import Toast, { type ToastState } from "../../components/Toast";

interface NodeFeatures {
  wbd_routing: boolean;
  benchmarking: boolean;
  frontier_sweep: boolean;
}

interface NodeConfig {
  version: number;
  llm: { api_base: string | null; model_name: string | null };
  allowed_org_ids: string[];
  features: NodeFeatures;
}

export default function SettingsPage() {
  return (
    <RoleGuard allowed={["admin"]}>
      <SettingsContent />
    </RoleGuard>
  );
}

function SettingsContent() {
  const { data: session } = useSession();
  const token = session?.user?.apiToken;

  const [config, setConfig] = useState<NodeConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [newOrgId, setNewOrgId] = useState("");

  const fetchConfig = useCallback(async () => {
    try {
      const data = await apiFetch<NodeConfig>("/api/v1/config", { token });
      setConfig(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load config");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) fetchConfig();
  }, [token, fetchConfig]);

  const saveConfig = async (updated: NodeConfig) => {
    setSaving(true);
    try {
      await apiFetch("/api/v1/config", {
        method: "POST",
        body: JSON.stringify(updated),
        token,
      });
      setConfig(updated);
      setToast({ type: "success", message: "Settings saved." });
    } catch (err) {
      setToast({
        type: "error",
        message: err instanceof Error ? err.message : "Save failed",
      });
    } finally {
      setSaving(false);
    }
  };

  const toggleFeature = (key: keyof NodeFeatures) => {
    if (!config) return;
    const updated = {
      ...config,
      features: { ...config.features, [key]: !config.features[key] },
    };
    saveConfig(updated);
  };

  const addOrgId = () => {
    if (!config || !newOrgId.trim()) return;
    const id = newOrgId.trim();
    if (config.allowed_org_ids.includes(id)) {
      setToast({ type: "error", message: "Org ID already in list." });
      return;
    }
    const updated = {
      ...config,
      allowed_org_ids: [...config.allowed_org_ids, id],
    };
    setNewOrgId("");
    saveConfig(updated);
  };

  const removeOrgId = (id: string) => {
    if (!config) return;
    const updated = {
      ...config,
      allowed_org_ids: config.allowed_org_ids.filter((o) => o !== id),
    };
    saveConfig(updated);
  };

  if (loading) {
    return (
      <div className="text-center py-12 text-gray-500">
        Loading settings...
      </div>
    );
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
      <h2 className="text-xl font-bold text-gray-900">Node Settings</h2>

      {/* Feature Flags */}
      <div className="bg-white shadow rounded-lg p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-1">
          Feature Flags
        </h3>
        <p className="text-sm text-gray-500 mb-4">
          Enable or disable node capabilities. Disabled features return 403 to
          callers.
        </p>
        <div className="space-y-3">
          {(
            [
              {
                key: "wbd_routing" as const,
                label: "WBD Routing",
                desc: "Accept and route Wisdom-Based Deferral tasks from agents",
              },
              {
                key: "benchmarking" as const,
                label: "Benchmarking",
                desc: "Allow HE-300 and SimpleBench evaluation runs",
              },
              {
                key: "frontier_sweep" as const,
                label: "Frontier Sweep",
                desc: "Launch frontier model sweep evaluations (admin)",
              },
            ] as const
          ).map(({ key, label, desc }) => (
            <div
              key={key}
              className="flex items-center justify-between border rounded p-4"
            >
              <div>
                <span className="font-medium text-gray-900">{label}</span>
                <p className="text-sm text-gray-500">{desc}</p>
              </div>
              <button
                onClick={() => toggleFeature(key)}
                disabled={saving}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  config?.features[key]
                    ? "bg-indigo-600"
                    : "bg-gray-300"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    config?.features[key]
                      ? "translate-x-6"
                      : "translate-x-1"
                  }`}
                />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Allowed Org IDs */}
      <div className="bg-white shadow rounded-lg p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-1">
          Allowed Organizations
        </h3>
        <p className="text-sm text-gray-500 mb-4">
          Registry/Portal org IDs this node will service. If empty, all
          organizations are allowed (open node). When set, only agents from
          listed orgs can register keys or submit WBD deferrals.
        </p>

        {/* Current list */}
        {config?.allowed_org_ids && config.allowed_org_ids.length > 0 ? (
          <div className="space-y-2 mb-4">
            {config.allowed_org_ids.map((id) => (
              <div
                key={id}
                className="flex items-center justify-between bg-gray-50 border rounded px-4 py-2"
              >
                <code className="text-sm font-mono text-gray-800">{id}</code>
                <button
                  onClick={() => removeOrgId(id)}
                  disabled={saving}
                  className="text-red-600 hover:text-red-800 text-sm font-medium disabled:opacity-50"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-amber-50 border border-amber-200 rounded p-3 mb-4">
            <p className="text-sm text-amber-800">
              No org restrictions set &mdash; this node is open to all
              organizations.
            </p>
          </div>
        )}

        {/* Add new */}
        <div className="flex gap-2">
          <input
            type="text"
            value={newOrgId}
            onChange={(e) => setNewOrgId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") addOrgId();
            }}
            placeholder="Org ID from Registry/Portal (e.g., 73bddb21-...)"
            className="flex-1 text-sm border border-gray-300 rounded px-3 py-2"
          />
          <button
            onClick={addOrgId}
            disabled={saving || !newOrgId.trim()}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            Add Org
          </button>
        </div>
      </div>

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
