"use client";

import React, { useState, useEffect, useCallback } from "react";

interface TracingStatus {
  enabled: boolean;
  initialized: boolean;
  project: string | null;
  has_client: boolean;
  has_tracer: boolean;
  endpoint: string | null;
}

interface TracingConfigProps {
  apiBaseUrl?: string;
}

export default function TracingConfig({ apiBaseUrl: propApiBaseUrl }: TracingConfigProps) {
  const [status, setStatus] = useState<TracingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = propApiBaseUrl || process.env.NEXT_PUBLIC_ETHICS_API_URL || "http://localhost:8080";

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/tracing/status`);
      if (!response.ok) {
        throw new Error(`Failed to fetch tracing status: ${response.statusText}`);
      }
      const data = await response.json();
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch status");
    } finally {
      setLoading(false);
    }
  }, [API_BASE]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  if (loading) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <div className="flex items-center gap-2">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
          <span className="text-gray-400">Loading tracing status...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-900/50 rounded-lg">
            <svg className="w-6 h-6 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">LangSmith Tracing</h3>
            <p className="text-sm text-gray-400">Monitor and debug LLM calls</p>
          </div>
        </div>
        
        {/* Status Badge */}
        <div className={`px-3 py-1 rounded-full text-sm font-medium ${
          status?.initialized 
            ? "bg-green-900/50 text-green-300" 
            : status?.enabled 
              ? "bg-yellow-900/50 text-yellow-300"
              : "bg-gray-700 text-gray-400"
        }`}>
          {status?.initialized ? "● Active" : status?.enabled ? "◌ Initializing" : "○ Disabled"}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/50 border border-red-700 rounded-md text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Status Details */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="bg-gray-900/50 rounded-lg p-3">
          <div className="text-xs text-gray-500 uppercase mb-1">Project</div>
          <div className="text-white font-mono text-sm">
            {status?.project || "—"}
          </div>
        </div>
        <div className="bg-gray-900/50 rounded-lg p-3">
          <div className="text-xs text-gray-500 uppercase mb-1">Components</div>
          <div className="flex gap-2 text-sm">
            <span className={`px-2 py-0.5 rounded ${status?.has_client ? "bg-green-900/50 text-green-300" : "bg-gray-700 text-gray-500"}`}>
              Client
            </span>
            <span className={`px-2 py-0.5 rounded ${status?.has_tracer ? "bg-green-900/50 text-green-300" : "bg-gray-700 text-gray-500"}`}>
              Tracer
            </span>
          </div>
        </div>
      </div>

      {/* Configuration Instructions */}
      <div className="border-t border-gray-700 pt-4">
        <h4 className="text-sm font-medium text-gray-300 mb-2">Configuration</h4>
        
        {status?.initialized ? (
          <div className="space-y-2">
            <p className="text-sm text-gray-400">
              ✓ LangSmith is active. View your traces at{" "}
              <a 
                href={`https://smith.langchain.com/o/default/projects/p/${status.project}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-purple-400 hover:underline"
              >
                smith.langchain.com
              </a>
            </p>
            <p className="text-xs text-gray-500">
              Endpoint: {status.endpoint}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-gray-400">
              To enable LangSmith tracing, add these environment variables:
            </p>
            <div className="bg-gray-900 rounded-md p-3 font-mono text-xs text-gray-300 overflow-x-auto">
              <div><span className="text-blue-400">LANGSMITH_ENABLED</span>=<span className="text-green-400">true</span></div>
              <div><span className="text-blue-400">LANGSMITH_API_KEY</span>=<span className="text-yellow-400">lsv2_...</span></div>
              <div><span className="text-blue-400">LANGSMITH_PROJECT</span>=<span className="text-green-400">ethicsengine</span></div>
            </div>
            <p className="text-xs text-gray-500">
              Get your API key at{" "}
              <a 
                href="https://smith.langchain.com/settings"
                target="_blank"
                rel="noopener noreferrer"
                className="text-purple-400 hover:underline"
              >
                smith.langchain.com/settings
              </a>
            </p>
          </div>
        )}
      </div>

      {/* Features List */}
      <div className="mt-4 border-t border-gray-700 pt-4">
        <h4 className="text-sm font-medium text-gray-300 mb-2">Features</h4>
        <ul className="grid grid-cols-2 gap-2 text-sm text-gray-400">
          <li className="flex items-center gap-2">
            <span className="text-purple-400">•</span> LLM call tracing
          </li>
          <li className="flex items-center gap-2">
            <span className="text-purple-400">•</span> Latency monitoring
          </li>
          <li className="flex items-center gap-2">
            <span className="text-purple-400">•</span> Token usage tracking
          </li>
          <li className="flex items-center gap-2">
            <span className="text-purple-400">•</span> Error debugging
          </li>
          <li className="flex items-center gap-2">
            <span className="text-purple-400">•</span> Prompt versioning
          </li>
          <li className="flex items-center gap-2">
            <span className="text-purple-400">•</span> Run comparison
          </li>
        </ul>
      </div>

      {/* Refresh Button */}
      <div className="mt-4 flex justify-end">
        <button
          onClick={fetchStatus}
          className="text-sm text-gray-400 hover:text-white transition-colors flex items-center gap-1"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </div>
    </div>
  );
}
