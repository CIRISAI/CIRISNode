"use client";
import React, { useState, useEffect } from 'react';
import ModelManager from '@/components/ModelManager';
import AgentBenchmarkRunner from '@/components/AgentBenchmarkRunner';
import ReportGenerator from '@/components/ReportGenerator';
import TracingConfig from '@/components/TracingConfig';
import GreenAgentConfig from '@/components/GreenAgentConfig';
import BaseLLMDemo from '@/components/BaseLLMDemo';
import EEEPurpleDemo from '@/components/EEEPurpleDemo';
import CIRISAgentDemo from '@/components/CIRISAgentDemo';
import CIRISBenchStatus from '@/components/CIRISBenchStatus';

interface CategoryBreakdown {
  [key: string]: {
    total: number;
    correct: number;
    accuracy: number;
    avg_latency_ms: number;
    errors: number;
  };
}

interface BenchmarkResult {
  batch_id: string;
  agent_name: string;
  model: string;
  accuracy: number;
  total_scenarios: number;
  correct: number;
  errors: number;
  categories: CategoryBreakdown;
  avg_latency_ms: number;
  processing_time_ms: number;
  concurrency_used: number;
  protocol: string;
  semantic_evaluation: boolean;
  random_seed: number | null;
  agent_card_name?: string;
  agent_card_version?: string;
  agent_card_provider?: string;
  agent_card_did?: string;
}

interface ApiHealth {
  status: string;
  version?: string;
}

interface HE300ContentProps {
  initialTab?: 'base-llm' | 'eee-purple' | 'ciris-agent' | 'models' | 'benchmark' | 'reports' | 'settings' | 'status';
}

export default function HE300Content({ initialTab = 'base-llm' }: HE300ContentProps) {
  const [activeTab, setActiveTab] = useState<'base-llm' | 'eee-purple' | 'ciris-agent' | 'models' | 'benchmark' | 'reports' | 'settings' | 'status'>(initialTab);
  const [apiBaseUrl, setApiBaseUrl] = useState<string | null>(null);
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null);
  const [lastBenchmarkResult, setLastBenchmarkResult] = useState<BenchmarkResult | null>(null);
  const [showApiConfig, setShowApiConfig] = useState(false);

  // Determine API base URL based on environment
  useEffect(() => {
    const envUrl = process.env.NEXT_PUBLIC_ETHICSENGINE_API || '';
    if (envUrl) {
      setApiBaseUrl(envUrl);
    } else if (typeof window !== 'undefined') {
      const host = window.location.hostname;
      if (host === 'localhost' || host === '127.0.0.1') {
        setApiBaseUrl('http://localhost:8080');
      } else {
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
  };

  const tabs = [
    { id: 'base-llm' as const, label: 'Base LLM', icon: '🟢' },
    { id: 'eee-purple' as const, label: 'EEE Purple', icon: '🟣' },
    { id: 'ciris-agent' as const, label: 'CIRIS Agent', icon: '🔮' },
    { id: 'benchmark' as const, label: 'Benchmark', icon: '🧪' },
    { id: 'models' as const, label: 'Models', icon: '🤖' },
    { id: 'reports' as const, label: 'Reports', icon: '📄' },
    { id: 'status' as const, label: 'Status', icon: '📡' },
    { id: 'settings' as const, label: 'Settings', icon: '⚙️' },
  ];

  if (apiBaseUrl === null) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-500 mx-auto"></div>
          <p className="mt-3 text-gray-600">Connecting to EthicsEngine...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Status Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 bg-white rounded-lg shadow-sm">
        <div className="flex items-center gap-3">
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
          <button
            onClick={() => setShowApiConfig(!showApiConfig)}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            ⚙️ Configure
          </button>
        </div>

        {lastBenchmarkResult && (
          <div className="flex items-center gap-2 px-3 py-1 bg-indigo-50 rounded-lg">
            <span className="text-sm text-indigo-700">
              Last: <strong>{(lastBenchmarkResult.accuracy * 100).toFixed(1)}%</strong>
            </span>
            <button
              onClick={() => setActiveTab('reports')}
              className="text-xs text-indigo-600 underline hover:text-indigo-800"
            >
              View Report →
            </button>
          </div>
        )}
      </div>

      {/* API Config (collapsible) */}
      {showApiConfig && (
        <div className="p-4 bg-gray-50 rounded-lg border">
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600">API Endpoint:</label>
            <input
              type="text"
              value={apiBaseUrl}
              onChange={(e) => setApiBaseUrl(e.target.value)}
              placeholder="http://localhost:8080"
              className="flex-1 max-w-md rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm"
            />
          </div>
        </div>
      )}

      {/* API connection warning */}
      {apiHealth?.status === 'unreachable' && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
          <h3 className="text-sm font-medium text-red-800">Cannot connect to EthicsEngine API</h3>
          <p className="mt-1 text-sm text-red-700">
            Make sure the API is running at <code className="bg-red-100 px-1 rounded">{apiBaseUrl}</code>
          </p>
        </div>
      )}

      {/* Sub-tabs for HE-300 */}
      <div className="bg-white rounded-lg shadow-sm">
        <div className="border-b border-gray-200">
          <nav className="flex flex-wrap gap-1 p-2" aria-label="HE-300 Tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'bg-indigo-100 text-indigo-700'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                }`}
              >
                <span className="mr-1">{tab.icon}</span>
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <div className="p-4">
          {activeTab === 'base-llm' && (
            <BaseLLMDemo apiBaseUrl={apiBaseUrl} />
          )}

          {activeTab === 'eee-purple' && (
            <EEEPurpleDemo apiBaseUrl={apiBaseUrl} />
          )}

          {activeTab === 'ciris-agent' && (
            <CIRISAgentDemo apiBaseUrl={apiBaseUrl} />
          )}

          {activeTab === 'models' && (
            <ModelManager apiBaseUrl={apiBaseUrl} />
          )}

          {activeTab === 'benchmark' && (
            <AgentBenchmarkRunner
              apiBaseUrl={apiBaseUrl}
              onBenchmarkComplete={handleBenchmarkComplete}
            />
          )}

          {activeTab === 'reports' && (
            <ReportGenerator apiBaseUrl={apiBaseUrl} />
          )}

          {activeTab === 'status' && (
            <CIRISBenchStatus apiBaseUrl={apiBaseUrl} />
          )}

          {activeTab === 'settings' && (
            <div className="space-y-6">
              <GreenAgentConfig apiBaseUrl={apiBaseUrl} />
              <TracingConfig apiBaseUrl={apiBaseUrl} />
            </div>
          )}
        </div>
      </div>

      {/* Quick Stats Footer */}
      {lastBenchmarkResult && (
        <div className="p-4 bg-white shadow-sm rounded-lg">
          <h3 className="text-sm font-medium text-gray-900 mb-3">Last Benchmark Summary</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-center">
            <div className="bg-gray-50 p-2 rounded">
              <p className="text-xl font-bold text-indigo-600">
                {(lastBenchmarkResult.accuracy * 100).toFixed(1)}%
              </p>
              <p className="text-xs text-gray-500">Accuracy</p>
            </div>
            <div className="bg-gray-50 p-2 rounded">
              <p className="text-xl font-bold text-gray-900">
                {lastBenchmarkResult.total_scenarios}
              </p>
              <p className="text-xs text-gray-500">Scenarios</p>
            </div>
            <div className="bg-gray-50 p-2 rounded">
              <p className="text-xl font-bold text-green-600">
                {lastBenchmarkResult.correct}
              </p>
              <p className="text-xs text-gray-500">Correct</p>
            </div>
            <div className="bg-gray-50 p-2 rounded">
              <p className="text-xl font-bold text-gray-900">
                {lastBenchmarkResult.avg_latency_ms.toFixed(0)}ms
              </p>
              <p className="text-xs text-gray-500">Latency</p>
            </div>
            <div className="bg-gray-50 p-2 rounded">
              <p className="text-xl font-bold text-red-600">
                {lastBenchmarkResult.errors}
              </p>
              <p className="text-xs text-gray-500">Errors</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
