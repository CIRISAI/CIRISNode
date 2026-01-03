"use client";
import React, { useState, useEffect, useCallback } from 'react';

interface ReportMetadata {
  report_id: string;
  batch_id: string;
  model_name?: string;
  accuracy?: number;
  format: string;
  created_at: string;
  file_path: string;
  file_size: number;
  signature?: {
    algorithm: string;
    content_hash: string;
    timestamp: string;
    signature: string;
  };
}

interface CategoryResult {
  total: number;
  correct: number;
  accuracy: number;
  avg_latency_ms: number;
  errors?: number;
}

interface BenchmarkSummary {
  batch_id: string;
  model_name: string;
  identity_id: string;
  guidance_id: string;
  total_scenarios: number;
  correct_predictions: number;
  overall_accuracy: number;
  avg_latency_ms: number;
  total_errors: number;
  categories: CategoryResult[];
  started_at: string;
  completed_at: string;
  processing_time_ms: number;
}

interface ScenarioDetail {
  scenario_id: string;
  category: string;
  input_text: string;
  expected_label: number | null;
  predicted_label: number | null;
  model_response: string;
  is_correct: boolean;
  latency_ms: number;
  error?: string | null;
}

interface ReportGeneratorProps {
  apiBaseUrl?: string;
  benchmarkResult?: {
    batch_id: string;
    summary: {
      total: number;
      correct: number;
      accuracy: number;
      avg_latency_ms: number;
      by_category: Record<string, CategoryResult>;
      errors: number;
    };
    identity_id: string;
    guidance_id: string;
    processing_time_ms: number;
    results: ScenarioDetail[];
  } | null;
}

const ReportGenerator: React.FC<ReportGeneratorProps> = ({ apiBaseUrl = '', benchmarkResult }) => {
  const [reports, setReports] = useState<ReportMetadata[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Report configuration
  const [format, setFormat] = useState<'markdown' | 'html' | 'json'>('markdown');
  const [includeScenarios, setIncludeScenarios] = useState(true);
  const [signReport, setSignReport] = useState(true);
  const [jekyllFrontmatter, setJekyllFrontmatter] = useState(true);
  const [title, setTitle] = useState('');
  const [modelName, setModelName] = useState('');

  const fetchReports = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${apiBaseUrl}/reports/`);
      if (!response.ok) throw new Error(`Failed to fetch reports: ${response.status}`);
      const data = await response.json();
      setReports(data.reports || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch reports');
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    fetchReports();
  }, [fetchReports]);

  const handleGenerateReport = async () => {
    if (!benchmarkResult) {
      setError('No benchmark result to generate report from. Run a benchmark first.');
      return;
    }

    setGenerating(true);
    setError(null);
    setSuccess(null);

    try {
      // Convert benchmark result to report format
      const now = new Date().toISOString();
      const summary: BenchmarkSummary = {
        batch_id: benchmarkResult.batch_id,
        model_name: modelName || 'Unknown Model',
        identity_id: benchmarkResult.identity_id,
        guidance_id: benchmarkResult.guidance_id,
        total_scenarios: benchmarkResult.summary.total,
        correct_predictions: benchmarkResult.summary.correct,
        overall_accuracy: benchmarkResult.summary.accuracy,
        avg_latency_ms: benchmarkResult.summary.avg_latency_ms,
        total_errors: benchmarkResult.summary.errors,
        categories: Object.entries(benchmarkResult.summary.by_category).map(([cat, stats]) => ({
          category: cat,
          total: stats.total,
          correct: stats.correct,
          accuracy: stats.accuracy,
          avg_latency_ms: stats.avg_latency_ms,
          errors: stats.errors || 0,
        })),
        started_at: now,
        completed_at: now,
        processing_time_ms: benchmarkResult.processing_time_ms,
      };

      const response = await fetch(`${apiBaseUrl}/reports/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batch_id: benchmarkResult.batch_id,
          summary,
          scenarios: includeScenarios ? benchmarkResult.results : [],
          format,
          include_scenarios: includeScenarios,
          sign_report: signReport,
          jekyll_frontmatter: jekyllFrontmatter,
          title: title || undefined,
          description: title || undefined,
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to generate report: ${response.status}`);
      }

      const data = await response.json();
      setSuccess(`Report generated: ${data.report_id}`);
      fetchReports();
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate report');
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = async (reportId: string) => {
    try {
      const response = await fetch(`${apiBaseUrl}/reports/download/${reportId}`);
      if (!response.ok) throw new Error('Download failed');
      
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report_${reportId}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed');
    }
  };

  const handleDelete = async (reportId: string) => {
    if (!confirm(`Delete report ${reportId}?`)) return;
    
    try {
      const response = await fetch(`${apiBaseUrl}/reports/${reportId}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Delete failed');
      fetchReports();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatDate = (iso: string): string => {
    return new Date(iso).toLocaleString();
  };

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-4 py-5 sm:px-6 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-medium text-gray-900">📄 Report Generator</h3>
            <p className="mt-1 text-sm text-gray-500">
              Generate signed static reports for Jekyll/GitHub Pages
            </p>
          </div>
          <button
            onClick={fetchReports}
            disabled={loading}
            className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
          >
            {loading ? 'Loading...' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-red-50 border-b border-red-200">
          <p className="text-sm text-red-700">⚠️ {error}</p>
        </div>
      )}

      {success && (
        <div className="px-4 py-3 bg-green-50 border-b border-green-200">
          <p className="text-sm text-green-700">✅ {success}</p>
        </div>
      )}

      {/* Generate Report Form */}
      <div className="p-4 bg-gray-50 border-b border-gray-200">
        <h4 className="text-sm font-medium text-gray-900 mb-4">Generate New Report</h4>
        
        {!benchmarkResult ? (
          <div className="p-4 bg-yellow-50 rounded-lg border border-yellow-200">
            <p className="text-sm text-yellow-800">
              ℹ️ Run a benchmark first to generate a report. The report will be based on the most recent benchmark result.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="p-3 bg-white rounded border border-gray-200">
              <p className="text-sm text-gray-600">
                <strong>Batch:</strong> {benchmarkResult.batch_id} |
                <strong> Scenarios:</strong> {benchmarkResult.summary.total} |
                <strong> Accuracy:</strong> {(benchmarkResult.summary.accuracy * 100).toFixed(1)}%
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {/* Format */}
              <div>
                <label htmlFor="format" className="block text-sm font-medium text-gray-700">
                  Output Format
                </label>
                <select
                  id="format"
                  value={format}
                  onChange={(e) => setFormat(e.target.value as 'markdown' | 'html' | 'json')}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                >
                  <option value="markdown">Markdown (Jekyll)</option>
                  <option value="html">HTML (Standalone)</option>
                  <option value="json">JSON (Machine-readable)</option>
                </select>
              </div>

              {/* Model Name */}
              <div>
                <label htmlFor="modelName" className="block text-sm font-medium text-gray-700">
                  Model Name
                </label>
                <input
                  type="text"
                  id="modelName"
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                  placeholder="e.g., gemma3:4b-it-q8_0"
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                />
              </div>

              {/* Title */}
              <div>
                <label htmlFor="title" className="block text-sm font-medium text-gray-700">
                  Report Title (optional)
                </label>
                <input
                  type="text"
                  id="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Auto-generated if empty"
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                />
              </div>
            </div>

            {/* Checkboxes */}
            <div className="flex flex-wrap gap-6">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={includeScenarios}
                  onChange={(e) => setIncludeScenarios(e.target.checked)}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                Include scenario details
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={signReport}
                  onChange={(e) => setSignReport(e.target.checked)}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                🔐 Sign report (integrity verification)
              </label>
              {format === 'markdown' && (
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={jekyllFrontmatter}
                    onChange={(e) => setJekyllFrontmatter(e.target.checked)}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  Jekyll YAML frontmatter
                </label>
              )}
            </div>

            <button
              onClick={handleGenerateReport}
              disabled={generating}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {generating ? (
                <>
                  <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Generating...
                </>
              ) : (
                <>📄 Generate Report</>
              )}
            </button>
          </div>
        )}
      </div>

      {/* Reports List */}
      <div className="divide-y divide-gray-200">
        <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
          <h4 className="text-sm font-medium text-gray-900">
            Generated Reports ({reports.length})
          </h4>
        </div>

        {reports.length === 0 && !loading && (
          <div className="px-4 py-8 text-center text-gray-500">
            <p>No reports generated yet.</p>
          </div>
        )}

        {reports.map((report) => (
          <div key={report.report_id} className="px-4 py-4 flex items-center justify-between hover:bg-gray-50">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-lg">
                  {report.format === 'markdown' ? '📝' : report.format === 'html' ? '🌐' : '📊'}
                </span>
                <code className="text-sm font-medium text-gray-900">{report.report_id}</code>
                {report.signature && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                    🔐 Signed
                  </span>
                )}
              </div>
              <div className="flex items-center gap-4 mt-1 text-xs text-gray-500">
                {report.model_name && <span className="font-medium text-indigo-600">🤖 {report.model_name}</span>}
                {report.accuracy !== undefined && (
                  <span className={`font-medium ${report.accuracy >= 0.8 ? 'text-green-600' : report.accuracy >= 0.5 ? 'text-yellow-600' : 'text-red-600'}`}>
                    📊 {(report.accuracy * 100).toFixed(1)}%
                  </span>
                )}
                <span>Batch: {report.batch_id}</span>
                <span>Format: {report.format}</span>
                <span>Size: {formatSize(report.file_size)}</span>
                <span>Created: {formatDate(report.created_at)}</span>
              </div>
            </div>
            <div className="flex items-center gap-2 ml-4">
              <button
                onClick={() => handleDownload(report.report_id)}
                className="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-indigo-700 bg-indigo-100 hover:bg-indigo-200"
              >
                ⬇️ Download
              </button>
              <button
                onClick={() => handleDelete(report.report_id)}
                className="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-red-700 bg-red-100 hover:bg-red-200"
              >
                🗑️ Delete
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* GitHub Pages Instructions */}
      <div className="px-4 py-4 bg-gray-50 border-t border-gray-200">
        <details>
          <summary className="text-sm font-medium text-gray-700 cursor-pointer hover:text-gray-900">
            📚 How to deploy reports to GitHub Pages
          </summary>
          <div className="mt-3 prose prose-sm text-gray-600">
            <ol className="list-decimal list-inside space-y-2">
              <li>Download the Markdown report with Jekyll frontmatter enabled</li>
              <li>Add the report to your Jekyll site&apos;s <code>_posts/</code> or <code>reports/</code> directory</li>
              <li>The report includes YAML frontmatter with metadata for Jekyll to process</li>
              <li>Push to GitHub and enable GitHub Pages in repository settings</li>
              <li>Reports include cryptographic signatures for integrity verification</li>
            </ol>
            <div className="mt-3 p-3 bg-white rounded border border-gray-200">
              <p className="text-xs font-medium text-gray-700 mb-2">Example Jekyll layout for reports:</p>
              <pre className="text-xs bg-gray-100 p-2 rounded overflow-x-auto">{`---
layout: default
---
<article class="report">
  <h1>{{ page.title }}</h1>
  <p class="meta">
    Model: {{ page.model }} | 
    Accuracy: {{ page.accuracy | times: 100 }}%
  </p>
  {{ content }}
</article>`}</pre>
            </div>
          </div>
        </details>
      </div>
    </div>
  );
};

export default ReportGenerator;
