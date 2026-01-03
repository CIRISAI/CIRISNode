"use client";

import React, { useState, useEffect, useCallback } from "react";

interface ReportResult {
  id: string;
  model_name: string;
  report_name: string;
  created_at: string;
  scores: Record<string, number>;
  status: string;
}

interface GitHubConfig {
  token: string;
  repo: string;
  branch: string;
}

interface ReportGeneratorProps {
  apiBaseUrl?: string;
}

// GitHub Config Modal Component
function GitHubConfigModal({
  isOpen,
  onClose,
  config,
  onSave,
}: {
  isOpen: boolean;
  onClose: () => void;
  config: GitHubConfig;
  onSave: (config: GitHubConfig) => void;
}) {
  const [localConfig, setLocalConfig] = useState<GitHubConfig>(config);

  useEffect(() => {
    setLocalConfig(config);
  }, [config]);

  if (!isOpen) return null;

  const handleSave = () => {
    onSave(localConfig);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md border border-gray-700">
        <h3 className="text-xl font-semibold text-white mb-4">GitHub Configuration</h3>
        
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              GitHub Personal Access Token
            </label>
            <input
              type="password"
              value={localConfig.token}
              onChange={(e) => setLocalConfig({ ...localConfig, token: e.target.value })}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="ghp_xxxxxxxxxxxx"
            />
            <p className="mt-1 text-xs text-gray-400">
              Requires repo scope. Create at{" "}
              <a
                href="https://github.com/settings/tokens"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400 hover:underline"
              >
                github.com/settings/tokens
              </a>
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Repository (owner/repo)
            </label>
            <input
              type="text"
              value={localConfig.repo}
              onChange={(e) => setLocalConfig({ ...localConfig, repo: e.target.value })}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="username/ethics-benchmarks"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Branch
            </label>
            <input
              type="text"
              value={localConfig.branch}
              onChange={(e) => setLocalConfig({ ...localConfig, branch: e.target.value })}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="gh-pages"
            />
          </div>
        </div>

        <div className="flex justify-end space-x-3 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white rounded-md transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-md transition-colors"
          >
            Save Configuration
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ReportGenerator({ apiBaseUrl: propApiBaseUrl }: ReportGeneratorProps) {
  const [results, setResults] = useState<ReportResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedResults, setSelectedResults] = useState<Set<string>>(new Set());
  const [generating, setGenerating] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishToGitHub, setPublishToGitHub] = useState(false);
  const [generateAllFormats, setGenerateAllFormats] = useState(true);
  const [showGitHubModal, setShowGitHubModal] = useState(false);
  const [gitHubConfig, setGitHubConfig] = useState<GitHubConfig>({
    token: "",
    repo: "",
    branch: "gh-pages",
  });
  const [publishStatus, setPublishStatus] = useState<string | null>(null);

  // Use ethicsengine API for reports (port 8080), not CIRISNode (port 8000)
  const API_BASE = propApiBaseUrl || process.env.NEXT_PUBLIC_ETHICS_API_URL || "http://localhost:8080";
  const STORAGE_KEY = "he300_github_config";

  // Load GitHub config from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        setGitHubConfig(parsed);
      }
    } catch (e) {
      console.error("Failed to load GitHub config from localStorage:", e);
    }
  }, []);

  // Save GitHub config to localStorage
  const saveGitHubConfig = useCallback((config: GitHubConfig) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
      setGitHubConfig(config);
    } catch (e) {
      console.error("Failed to save GitHub config to localStorage:", e);
    }
  }, []);

  // Fetch available results
  useEffect(() => {
    const fetchResults = async () => {
      try {
        setLoading(true);
        const response = await fetch(`${API_BASE}/reports/results`);
        if (!response.ok) {
          throw new Error(`Failed to fetch results: ${response.statusText}`);
        }
        const data = await response.json();
        setResults(data.results || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch results");
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, [API_BASE]);

  const toggleResultSelection = (id: string) => {
    const newSelected = new Set(selectedResults);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelectedResults(newSelected);
  };

  const selectAll = () => {
    if (selectedResults.size === results.length) {
      setSelectedResults(new Set());
    } else {
      setSelectedResults(new Set(results.map((r) => r.id)));
    }
  };

  const handleGenerateReports = async () => {
    if (selectedResults.size === 0) {
      setError("Please select at least one result to generate reports");
      return;
    }

    // Check GitHub config if publishing is enabled
    if (publishToGitHub && (!gitHubConfig.token || !gitHubConfig.repo)) {
      setShowGitHubModal(true);
      return;
    }

    setGenerating(true);
    setError(null);
    setPublishStatus(null);

    try {
      const formats = generateAllFormats
        ? ["markdown", "html", "json"]
        : ["markdown"];

      // Generate reports for selected results
      const response = await fetch(`${API_BASE}/reports/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          result_ids: Array.from(selectedResults),
          formats: formats,
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to generate reports: ${response.statusText}`);
      }

      const data = await response.json();
      setPublishStatus(`Generated ${data.reports?.length || 0} reports`);

      // If publishing to GitHub is enabled, deploy the reports
      if (publishToGitHub) {
        setPublishing(true);
        await handleGitHubDeploy();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate reports");
    } finally {
      setGenerating(false);
      setPublishing(false);
    }
  };

  const handleGitHubDeploy = async () => {
    try {
      const response = await fetch(`${API_BASE}/github/deploy`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          token: gitHubConfig.token,
          repo: gitHubConfig.repo,
          branch: gitHubConfig.branch,
          result_ids: Array.from(selectedResults),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Deploy failed: ${response.statusText}`);
      }

      await response.json();
      setPublishStatus(
        `✓ Published to GitHub Pages! View at: https://${gitHubConfig.repo.split("/")[0]}.github.io/${gitHubConfig.repo.split("/")[1]}/`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to deploy to GitHub");
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const getOverallScore = (scores: Record<string, number>) => {
    const values = Object.values(scores);
    if (values.length === 0) return 0;
    return (values.reduce((a, b) => a + b, 0) / values.length) * 100;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <GitHubConfigModal
        isOpen={showGitHubModal}
        onClose={() => setShowGitHubModal(false)}
        config={gitHubConfig}
        onSave={saveGitHubConfig}
      />

      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-white">Report Generator</h2>
          <p className="text-gray-400 mt-1">
            Select benchmark results to generate and optionally publish reports
          </p>
        </div>
        <button
          onClick={() => setShowGitHubModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-md transition-colors"
        >
          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
          </svg>
          Configure GitHub
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-900/50 border border-red-700 text-red-200 px-4 py-3 rounded-md">
          {error}
          <button
            onClick={() => setError(null)}
            className="float-right text-red-200 hover:text-white"
          >
            ×
          </button>
        </div>
      )}

      {/* Success/Status Display */}
      {publishStatus && (
        <div className="bg-green-900/50 border border-green-700 text-green-200 px-4 py-3 rounded-md">
          {publishStatus}
        </div>
      )}

      {/* Options Panel */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h3 className="text-lg font-medium text-white mb-4">Generation Options</h3>
        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={generateAllFormats}
              onChange={(e) => setGenerateAllFormats(e.target.checked)}
              className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500 focus:ring-offset-gray-800"
            />
            <span className="text-gray-300">Generate all formats (Markdown, HTML, JSON)</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={publishToGitHub}
              onChange={(e) => setPublishToGitHub(e.target.checked)}
              className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500 focus:ring-offset-gray-800"
            />
            <span className="text-gray-300">Publish to GitHub Pages</span>
            {publishToGitHub && gitHubConfig.token && (
              <span className="text-green-400 text-sm">(configured)</span>
            )}
            {publishToGitHub && !gitHubConfig.token && (
              <span className="text-yellow-400 text-sm">(not configured)</span>
            )}
          </label>
        </div>
      </div>

      {/* Results Table */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
        <div className="px-4 py-3 bg-gray-750 border-b border-gray-700 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedResults.size === results.length && results.length > 0}
                onChange={selectAll}
                className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500 focus:ring-offset-gray-800"
              />
              <span className="text-gray-300 text-sm">Select All</span>
            </label>
            <span className="text-gray-400 text-sm">
              {selectedResults.size} of {results.length} selected
            </span>
          </div>
          <button
            onClick={handleGenerateReports}
            disabled={selectedResults.size === 0 || generating || publishing}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-md transition-colors flex items-center gap-2"
          >
            {generating || publishing ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                {publishing ? "Publishing..." : "Generating..."}
              </>
            ) : (
              <>
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                  />
                </svg>
                Generate Reports
              </>
            )}
          </button>
        </div>

        {results.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-400">
            No benchmark results available. Run some benchmarks first!
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-gray-750">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider w-12">
                  Select
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Model
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Benchmark
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Score
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Date
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {results.map((result) => (
                <tr
                  key={result.id}
                  className={`hover:bg-gray-750 cursor-pointer ${
                    selectedResults.has(result.id) ? "bg-blue-900/20" : ""
                  }`}
                  onClick={() => toggleResultSelection(result.id)}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedResults.has(result.id)}
                      onChange={() => toggleResultSelection(result.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500 focus:ring-offset-gray-800"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-white">{result.model_name}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-sm text-gray-300">{result.report_name}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-gray-700 rounded-full max-w-24">
                        <div
                          className="h-2 bg-gradient-to-r from-blue-500 to-green-500 rounded-full"
                          style={{ width: `${getOverallScore(result.scores)}%` }}
                        ></div>
                      </div>
                      <span className="text-sm text-gray-300">
                        {getOverallScore(result.scores).toFixed(1)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-sm text-gray-400">{formatDate(result.created_at)}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        result.status === "completed"
                          ? "bg-green-900/50 text-green-300"
                          : result.status === "running"
                          ? "bg-yellow-900/50 text-yellow-300"
                          : "bg-gray-700 text-gray-300"
                      }`}
                    >
                      {result.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* GitHub Pages Link */}
      {gitHubConfig.repo && (
        <div className="text-center text-gray-400 text-sm">
          GitHub Pages URL:{" "}
          <a
            href={`https://${gitHubConfig.repo.split("/")[0]}.github.io/${gitHubConfig.repo.split("/")[1]}/`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:underline"
          >
            https://{gitHubConfig.repo.split("/")[0]}.github.io/{gitHubConfig.repo.split("/")[1]}/
          </a>
        </div>
      )}
    </div>
  );
}
