"use client";
import React, { useState, useEffect, useCallback } from 'react';
import { useGreenAgentSettings } from './GreenAgentConfig';

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
  // Agent card info
  agent_card_name?: string;
  agent_card_version?: string;
  agent_card_provider?: string;
  agent_card_did?: string;
}

interface AgentBenchmarkRunnerProps {
  apiBaseUrl?: string;
  onBenchmarkComplete?: (result: BenchmarkResult) => void;
}

// HE-300 categories per spec
const HE300_CATEGORIES = [
  'commonsense',
  'commonsense_hard',
  'deontology',
  'justice',
  'virtue',
];

const AgentBenchmarkRunner: React.FC<AgentBenchmarkRunnerProps> = ({
  apiBaseUrl = '',
  onBenchmarkComplete
}) => {
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BenchmarkResult | null>(null);
  const [progress, setProgress] = useState<string>('');

  // Configuration
  const [agentUrl, setAgentUrl] = useState<string>('http://localhost:9000/a2a');
  const [agentName, setAgentName] = useState<string>('Purple Agent');
  const [modelName, setModelName] = useState<string>('');
  const [sampleSize, setSampleSize] = useState<number>(60);
  const [concurrency, setConcurrency] = useState<number>(10);
  const [randomSeed, setRandomSeed] = useState<string>('');
  const [protocol, setProtocol] = useState<'a2a' | 'mcp'>('a2a');
  const [semanticEval, setSemanticEval] = useState<boolean>(true);

  // Green Agent (Evaluator) config from Settings
  const { settings: greenAgentSettings } = useGreenAgentSettings();

  // API health
  const [apiHealth, setApiHealth] = useState<'unknown' | 'healthy' | 'unhealthy'>('unknown');

  // Check API health
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/health`, {
          signal: AbortSignal.timeout(5000)
        });
        if (response.ok) {
          setApiHealth('healthy');
        } else {
          setApiHealth('unhealthy');
        }
      } catch {
        setApiHealth('unhealthy');
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, [apiBaseUrl]);

  // Calculate category distribution per HE-300 spec
  const getCategoryDistribution = useCallback((total: number) => {
    const numCategories = HE300_CATEGORIES.length;
    const perCategory = Math.floor(total / numCategories);
    const remainder = total % numCategories;

    return HE300_CATEGORIES.map((cat, idx) => ({
      category: cat,
      count: perCategory + (idx < remainder ? 1 : 0)
    }));
  }, []);

  const handleRunBenchmark = async (e: React.FormEvent) => {
    e.preventDefault();
    setRunning(true);
    setError(null);
    setResult(null);
    setProgress('Initializing benchmark...');

    try {
      // Validate agent URL
      if (!agentUrl) {
        throw new Error('Agent URL is required');
      }

      setProgress('Connecting to agent and fetching agent card...');

      // Build request
      const request: Record<string, unknown> = {
        agent_url: agentUrl,
        agent_name: agentName || 'Purple Agent',
        model: modelName || 'unknown',
        protocol: protocol,
        sample_size: sampleSize,
        concurrency: concurrency,
        semantic_evaluation: semanticEval,
        random_seed: randomSeed ? parseInt(randomSeed) : null,
        timeout_per_scenario: 60,
        verify_ssl: true,
      };

      // Add evaluator LLM config from Settings (overrides server .env defaults)
      if (greenAgentSettings.provider) {
        request.evaluator_provider = greenAgentSettings.provider;
      }
      if (greenAgentSettings.model) {
        request.evaluator_model = greenAgentSettings.model;
      }
      if (greenAgentSettings.apiKey) {
        request.evaluator_api_key = greenAgentSettings.apiKey;
      }

      setProgress(`Running ${sampleSize} scenarios across ${HE300_CATEGORIES.length} categories (${Math.floor(sampleSize / HE300_CATEGORIES.length)} per category)...`);

      const response = await fetch(`${apiBaseUrl}/he300/agentbeats/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Benchmark failed: ${response.status}`);
      }

      const benchmarkResult: BenchmarkResult = await response.json();
      setResult(benchmarkResult);
      setProgress('');

      if (onBenchmarkComplete) {
        onBenchmarkComplete(benchmarkResult);
      }

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Benchmark failed');
      setProgress('');
    } finally {
      setRunning(false);
    }
  };

  const distribution = getCategoryDistribution(sampleSize);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-indigo-600 to-purple-600 rounded-lg p-6 text-white">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <span>🎯</span> Agent Benchmark Runner
        </h2>
        <p className="mt-2 text-indigo-100">
          Run HE-300 ethics benchmark against any A2A/MCP compatible agent
        </p>
        <div className="mt-2 flex items-center gap-2">
          <span className="px-2 py-1 bg-indigo-500 bg-opacity-30 rounded text-xs font-medium">
            Supported: A2A, MCP
          </span>
          <span className="px-2 py-1 bg-indigo-500 bg-opacity-30 rounded text-xs font-mono">
            POST /he300/agentbeats/run
          </span>
        </div>
      </div>

      {/* Configuration Panel */}
      <div className="bg-white shadow rounded-lg p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">Configuration</h3>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleRunBenchmark} className="space-y-6">
          {/* Agent Connection */}
          <div className="border-b border-gray-200 pb-6">
            <h4 className="text-sm font-medium text-gray-700 mb-3">Agent Connection</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Agent URL *
                </label>
                <input
                  type="url"
                  value={agentUrl}
                  onChange={(e) => setAgentUrl(e.target.value)}
                  placeholder={protocol === 'a2a' ? 'http://localhost:9000/a2a' : 'http://localhost:9000/mcp'}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                  required
                />
                <p className="mt-1 text-xs text-gray-500">
                  {protocol === 'a2a'
                    ? 'A2A endpoint (e.g., http://localhost:9000/a2a)'
                    : 'MCP endpoint (e.g., http://localhost:9000/mcp)'}
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Agent Name
                </label>
                <input
                  type="text"
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder="My Purple Agent"
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Model Name
                </label>
                <input
                  type="text"
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                  placeholder="gpt-4o, claude-3, llama-3.3"
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Protocol
                </label>
                <select
                  value={protocol}
                  onChange={(e) => setProtocol(e.target.value as 'a2a' | 'mcp')}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                >
                  <option value="a2a">A2A (Agent-to-Agent)</option>
                  <option value="mcp">MCP (Model Context Protocol)</option>
                </select>
              </div>
            </div>
          </div>

          {/* Benchmark Settings */}
          <div className="border-b border-gray-200 pb-6">
            <h4 className="text-sm font-medium text-gray-700 mb-3">Benchmark Settings</h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Sample Size
                </label>
                <select
                  value={sampleSize}
                  onChange={(e) => setSampleSize(parseInt(e.target.value))}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                >
                  <option value={10}>10 (Quick test)</option>
                  <option value={30}>30 (6 per category)</option>
                  <option value={60}>60 (12 per category)</option>
                  <option value={150}>150 (30 per category)</option>
                  <option value={300}>300 (Full HE-300)</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Concurrency
                </label>
                <select
                  value={concurrency}
                  onChange={(e) => setConcurrency(parseInt(e.target.value))}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                >
                  <option value={10}>10 (Conservative)</option>
                  <option value={50}>50 (Default)</option>
                  <option value={100}>100 (Aggressive)</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Random Seed (optional)
                </label>
                <input
                  type="number"
                  value={randomSeed}
                  onChange={(e) => setRandomSeed(e.target.value)}
                  placeholder="Auto-generated"
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                />
                <p className="mt-1 text-xs text-gray-500">
                  For reproducible scenario selection
                </p>
              </div>
            </div>

            <div className="mt-4">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={semanticEval}
                  onChange={(e) => setSemanticEval(e.target.checked)}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-sm text-gray-700">
                  Enable semantic evaluation (LLM-based response classification)
                </span>
              </label>
            </div>
          </div>

          {/* Green Agent Config Reference */}
          {semanticEval && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-green-600">🟢</span>
                  <span className="text-sm text-green-800">
                    Green Agent: {greenAgentSettings.provider || 'Server Default'}
                    {greenAgentSettings.model && ` / ${greenAgentSettings.model}`}
                  </span>
                </div>
                <span className="text-xs text-green-600">
                  Configure in Settings tab
                </span>
              </div>
            </div>
          )}

          {/* Category Distribution Preview */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3">
              Category Distribution (per HE-300 spec)
            </h4>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              {distribution.map(({ category, count }) => (
                <div key={category} className="bg-white rounded p-2 text-center border border-gray-200">
                  <p className="text-xs text-gray-500 truncate" title={category}>{category}</p>
                  <p className="text-lg font-bold text-indigo-600">{count}</p>
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-gray-500">
              Scenarios are deterministically sampled from each category using the random seed
            </p>
          </div>

          {/* Run Button */}
          <div className="flex items-center gap-4">
            <button
              type="submit"
              disabled={running || apiHealth !== 'healthy'}
              className="px-6 py-3 bg-indigo-600 text-white font-medium rounded-md hover:bg-indigo-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {running ? (
                <>
                  <svg className="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Running Benchmark...
                </>
              ) : (
                <>🚀 Run Agent Benchmark</>
              )}
            </button>

            <div className="flex items-center gap-2">
              <span className={`inline-flex items-center px-3 py-1 rounded-md text-sm font-medium ${
                apiHealth === 'healthy'
                  ? 'bg-green-100 text-green-800'
                  : apiHealth === 'unhealthy'
                  ? 'bg-red-100 text-red-800'
                  : 'bg-gray-100 text-gray-800'
              }`}>
                {apiHealth === 'healthy' ? '● API Online' : apiHealth === 'unhealthy' ? '○ API Offline' : '◌ Checking'}
              </span>
            </div>
          </div>

          {progress && (
            <div className="p-3 bg-indigo-50 border border-indigo-200 rounded-md text-indigo-700 text-sm">
              {progress}
            </div>
          )}
        </form>
      </div>

      {/* Results */}
      {result && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-medium text-gray-900">
                  Benchmark Results
                </h3>
                <p className="text-sm text-gray-500">
                  Batch ID: {result.batch_id}
                </p>
              </div>
              <div className="text-right">
                <p className={`text-3xl font-bold ${
                  result.accuracy >= 0.8 ? 'text-green-600' :
                  result.accuracy >= 0.5 ? 'text-yellow-600' :
                  'text-red-600'
                }`}>
                  {(result.accuracy * 100).toFixed(1)}%
                </p>
                <p className="text-sm text-gray-500">accuracy</p>
              </div>
            </div>
          </div>

          {/* Agent Card Info */}
          {result.agent_card_name && (
            <div className="px-6 py-3 bg-pink-50 border-b border-pink-200">
              <div className="flex items-center gap-3">
                <span className="px-3 py-1 bg-pink-200 text-pink-800 rounded-full text-sm font-medium">
                  🎫 {result.agent_card_name}
                </span>
                {result.agent_card_version && (
                  <span className="text-sm text-pink-700">v{result.agent_card_version}</span>
                )}
                {result.agent_card_provider && (
                  <span className="text-sm text-pink-600">by {result.agent_card_provider}</span>
                )}
                {result.agent_card_did && (
                  <code className="text-xs bg-pink-100 px-2 py-0.5 rounded text-pink-700">
                    {result.agent_card_did}
                  </code>
                )}
              </div>
            </div>
          )}

          {/* Summary Stats */}
          <div className="p-6">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
              <div className="bg-gray-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-gray-900">{result.total_scenarios}</p>
                <p className="text-xs text-gray-500">Total</p>
              </div>
              <div className="bg-green-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-green-600">{result.correct}</p>
                <p className="text-xs text-gray-500">Correct</p>
              </div>
              <div className="bg-red-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-red-600">{result.errors}</p>
                <p className="text-xs text-gray-500">Errors</p>
              </div>
              <div className="bg-blue-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-blue-600">{result.avg_latency_ms.toFixed(0)}ms</p>
                <p className="text-xs text-gray-500">Avg Latency</p>
              </div>
              <div className="bg-purple-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-purple-600">{(result.processing_time_ms / 1000).toFixed(1)}s</p>
                <p className="text-xs text-gray-500">Total Time</p>
              </div>
            </div>

            {/* Category Breakdown */}
            <h4 className="text-sm font-medium text-gray-700 mb-3">Results by Category</h4>
            <div className="space-y-2">
              {Object.entries(result.categories).map(([cat, stats]) => (
                <div key={cat} className="flex items-center gap-3">
                  <span className="text-sm font-medium w-36 truncate" title={cat}>{cat}</span>
                  <div className="flex-1 h-3 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all ${
                        stats.accuracy >= 0.8 ? 'bg-green-500' :
                        stats.accuracy >= 0.5 ? 'bg-yellow-500' :
                        'bg-red-500'
                      }`}
                      style={{ width: `${stats.accuracy * 100}%` }}
                    />
                  </div>
                  <span className="text-sm text-gray-600 w-20 text-right">
                    {(stats.accuracy * 100).toFixed(1)}% ({stats.correct}/{stats.total})
                  </span>
                </div>
              ))}
            </div>

            {/* Metadata */}
            <div className="mt-6 pt-4 border-t border-gray-200">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Agent:</span>
                  <span className="ml-2 font-medium">{result.agent_name}</span>
                </div>
                <div>
                  <span className="text-gray-500">Model:</span>
                  <span className="ml-2 font-medium">{result.model}</span>
                </div>
                <div>
                  <span className="text-gray-500">Protocol:</span>
                  <span className="ml-2 font-medium uppercase">{result.protocol}</span>
                </div>
                <div>
                  <span className="text-gray-500">Concurrency:</span>
                  <span className="ml-2 font-medium">{result.concurrency_used}</span>
                </div>
                {result.random_seed && (
                  <div>
                    <span className="text-gray-500">Seed:</span>
                    <span className="ml-2 font-mono">{result.random_seed}</span>
                  </div>
                )}
                <div>
                  <span className="text-gray-500">Semantic Eval:</span>
                  <span className="ml-2 font-medium">{result.semantic_evaluation ? 'Yes' : 'No'}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AgentBenchmarkRunner;
