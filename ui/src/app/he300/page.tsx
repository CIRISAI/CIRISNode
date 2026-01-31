"use client";
import React, { useState, useEffect } from 'react';
import ModelManager from '@/components/ModelManager';
import HE300Runner from '@/components/HE300Runner';
import ReportGenerator from '@/components/ReportGenerator';
import TracingConfig from '@/components/TracingConfig';
import PurpleAgentDemo from '@/components/PurpleAgentDemo';

// Type for benchmark result that can be passed to report generator
interface ScenarioResult {
  scenario_id: string;
  category: string;
  input_text: string;
  expected_label: number | null;
  predicted_label: number | null;
  model_response: string;
  is_correct: boolean;
  latency_ms: number;
  error: string | null;
  trace_id?: string | null;
  trace_url?: string | null;
}

interface CategoryResult {
  total: number;
  correct: number;
  accuracy: number;
  avg_latency_ms: number;
  errors: number;
}

interface BenchmarkResult {
  batch_id: string;
  status: string;
  results: ScenarioResult[];
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
  model_name?: string;
}

interface ApiHealth {
  status: string;
  version?: string;
}

export default function HE300Dashboard() {
  const [activeTab, setActiveTab] = useState<'demo' | 'models' | 'benchmark' | 'reports' | 'settings'>('demo');
  const [apiBaseUrl, setApiBaseUrl] = useState<string | null>(null);
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null);
  const [lastBenchmarkResult, setLastBenchmarkResult] = useState<BenchmarkResult | null>(null);

  // Determine API base URL based on environment
  useEffect(() => {
    // In development, use the proxy configured in next.config
    // In production/docker, use environment variable or default
    const envUrl = process.env.NEXT_PUBLIC_ETHICSENGINE_API || '';
    if (envUrl) {
      setApiBaseUrl(envUrl);
    } else if (typeof window !== 'undefined') {
      // Try to auto-detect based on current URL
      const host = window.location.hostname;
      if (host === 'localhost' || host === '127.0.0.1') {
        // Development - use port 8080 for EthicsEngine
        setApiBaseUrl('http://localhost:8080');
      } else {
        // Production - assume same host, different port or path
        setApiBaseUrl(`http://${host}:8080`);
      }
    }
  }, []);

  // Check API health
  useEffect(() => {
    if (!apiBaseUrl) return;

    const checkHealth = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/health`);
        if (response.ok) {
          const data = await response.json();
          setApiHealth({ status: 'healthy', version: data.version });
        } else {
          setApiHealth({ status: 'unhealthy' });
        }
      } catch {
        setApiHealth({ status: 'unreachable' });
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, [apiBaseUrl]);

  const handleBenchmarkComplete = (result: BenchmarkResult) => {
    setLastBenchmarkResult(result);
    // Optionally auto-switch to reports tab
    // setActiveTab('reports');
  };

  const tabs = [
    { id: 'demo' as const, label: '🟣 Purple Agent Demo', icon: '🟣' },
    { id: 'benchmark' as const, label: '🧪 Benchmark', icon: '🧪' },
    { id: 'models' as const, label: '🤖 Models', icon: '🤖' },
    { id: 'reports' as const, label: '📄 Reports & Publishing', icon: '📄' },
    { id: 'settings' as const, label: '⚙️ Settings', icon: '⚙️' },
  ];

  // Don't render until API URL is determined
  if (apiBaseUrl === null) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500 mx-auto"></div>
          <p className="mt-4 text-gray-600">Initializing...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                ⚖️ HE-300 Ethics Benchmark
              </h1>
              <p className="mt-1 text-sm text-gray-500">
                Hendrycks Ethics Benchmark Dashboard - Run tests, manage models, generate reports
              </p>
            </div>
            <div className="flex items-center gap-4">
              {/* API Status */}
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  apiHealth?.status === 'healthy' 
                    ? 'bg-green-100 text-green-800' 
                    : apiHealth?.status === 'unreachable'
                    ? 'bg-red-100 text-red-800'
                    : 'bg-yellow-100 text-yellow-800'
                }`}>
                  {apiHealth?.status === 'healthy' ? '● API Connected' : 
                   apiHealth?.status === 'unreachable' ? '○ API Unreachable' : 
                   '◌ Connecting...'}
                </span>
                {apiHealth?.version && (
                  <span className="text-xs text-gray-500">v{apiHealth.version}</span>
                )}
              </div>
              
              {/* Last result indicator */}
              {lastBenchmarkResult && (
                <div className="flex items-center gap-2 px-3 py-1 bg-indigo-50 rounded-lg">
                  <span className="text-sm text-indigo-700">
                    Last run: <strong>{(lastBenchmarkResult.summary.accuracy * 100).toFixed(1)}%</strong> accuracy
                  </span>
                  <button
                    onClick={() => setActiveTab('reports')}
                    className="text-xs text-indigo-600 underline hover:text-indigo-800"
                  >
                    Generate Report →
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* API URL Config (collapsible) */}
          <details className="mt-4">
            <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-700">
              ⚙️ Configure API endpoint
            </summary>
            <div className="mt-2 flex items-center gap-2">
              <input
                type="text"
                value={apiBaseUrl}
                onChange={(e) => setApiBaseUrl(e.target.value)}
                placeholder="http://localhost:8080"
                className="flex-1 max-w-md rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
              />
              <span className="text-xs text-gray-500">
                EthicsEngine API endpoint
              </span>
            </div>
          </details>
        </div>
      </header>

      {/* Tab Navigation */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <nav className="flex space-x-8" aria-label="Tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-4 px-1 border-b-2 font-medium text-sm ${
                  activeTab === tab.id
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* API connection warning */}
        {apiHealth?.status === 'unreachable' && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
            <h3 className="text-sm font-medium text-red-800">⚠️ Cannot connect to EthicsEngine API</h3>
            <p className="mt-1 text-sm text-red-700">
              Make sure the EthicsEngine API is running at <code className="bg-red-100 px-1 rounded">{apiBaseUrl}</code>
            </p>
            <p className="mt-2 text-sm text-red-600">
              If using SSH tunnel: <code className="bg-red-100 px-1 rounded">ssh -L 8080:localhost:8080 ubuntu@server</code>
            </p>
          </div>
        )}

        {/* Tab Content */}
        <div className="space-y-6">
          {activeTab === 'demo' && (
            <PurpleAgentDemo apiBaseUrl={apiBaseUrl} />
          )}

          {activeTab === 'models' && (
            <ModelManager apiBaseUrl={apiBaseUrl} />
          )}

          {activeTab === 'benchmark' && (
            <HE300Runner 
              apiBaseUrl={apiBaseUrl} 
              onBenchmarkComplete={handleBenchmarkComplete}
            />
          )}

          {activeTab === 'reports' && (
            <ReportGenerator 
              apiBaseUrl={apiBaseUrl} 
            />
          )}

          {activeTab === 'settings' && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-semibold text-gray-900 mb-4">System Settings</h2>
                <TracingConfig apiBaseUrl={apiBaseUrl} />
              </div>
            </div>
          )}
        </div>

        {/* Quick Stats Footer */}
        {lastBenchmarkResult && (
          <div className="mt-8 p-4 bg-white shadow rounded-lg">
            <h3 className="text-sm font-medium text-gray-900 mb-3">📊 Last Benchmark Summary</h3>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-center">
              <div className="bg-gray-50 p-3 rounded">
                <p className="text-2xl font-bold text-indigo-600">
                  {(lastBenchmarkResult.summary.accuracy * 100).toFixed(1)}%
                </p>
                <p className="text-xs text-gray-500">Accuracy</p>
              </div>
              <div className="bg-gray-50 p-3 rounded">
                <p className="text-2xl font-bold text-gray-900">
                  {lastBenchmarkResult.summary.total}
                </p>
                <p className="text-xs text-gray-500">Scenarios</p>
              </div>
              <div className="bg-gray-50 p-3 rounded">
                <p className="text-2xl font-bold text-green-600">
                  {lastBenchmarkResult.summary.correct}
                </p>
                <p className="text-xs text-gray-500">Correct</p>
              </div>
              <div className="bg-gray-50 p-3 rounded">
                <p className="text-2xl font-bold text-gray-900">
                  {lastBenchmarkResult.summary.avg_latency_ms.toFixed(0)}ms
                </p>
                <p className="text-xs text-gray-500">Avg Latency</p>
              </div>
              <div className="bg-gray-50 p-3 rounded">
                <p className="text-2xl font-bold text-red-600">
                  {lastBenchmarkResult.summary.errors}
                </p>
                <p className="text-xs text-gray-500">Errors</p>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <p className="text-center text-sm text-gray-500">
            EthicsEngine Enterprise × CIRISNode | HE-300 Hendrycks Ethics Benchmark
          </p>
        </div>
      </footer>
    </div>
  );
}
