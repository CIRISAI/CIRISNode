"use client";
import React, { useState, useEffect, useCallback } from 'react';

interface CategoryResult {
  category: string;
  total: number;
  correct: number;
  accuracy: number;
  avg_latency_ms: number;
  errors: number;
}

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
}

interface BatchResult {
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
}

interface CatalogInfo {
  total_scenarios: number;
  by_category: Record<string, number>;
}

interface HE300RunnerProps {
  apiBaseUrl?: string;
  onBenchmarkComplete?: (result: BatchResult) => void;
}

const HE300Runner: React.FC<HE300RunnerProps> = ({ apiBaseUrl = '', onBenchmarkComplete }) => {
  const [catalog, setCatalog] = useState<CatalogInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);
  
  // Configuration
  const [category, setCategory] = useState<string>('commonsense');
  const [numScenarios, setNumScenarios] = useState<number>(10);
  const [identityId, setIdentityId] = useState<string>('Neutral');
  const [guidanceId, setGuidanceId] = useState<string>('Utilitarian');
  const [batchId, setBatchId] = useState<string>('');
  
  // Available models from Ollama
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');

  const fetchCatalog = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/he300/catalog?limit=0`);
      if (!response.ok) throw new Error(`Failed to fetch catalog: ${response.status}`);
      const data = await response.json();
      setCatalog({
        total_scenarios: data.total_scenarios,
        by_category: data.by_category,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch catalog');
    }
  }, [apiBaseUrl]);

  const fetchModels = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/ollama/models`);
      if (!response.ok) return;
      const data = await response.json();
      const modelNames = (data.models || []).map((m: { name: string }) => m.name);
      setModels(modelNames);
      if (modelNames.length > 0 && !selectedModel) {
        setSelectedModel(modelNames[0]);
      }
    } catch {
      // Silently fail - models are optional
    }
  }, [apiBaseUrl, selectedModel]);

  useEffect(() => {
    fetchCatalog();
    fetchModels();
    // Generate default batch ID
    setBatchId(`he300-${Date.now().toString(36)}`);
  }, [fetchCatalog, fetchModels]);

  const handleRunBenchmark = async (e: React.FormEvent) => {
    e.preventDefault();
    setRunning(true);
    setError(null);
    setResult(null);

    try {
      // First, fetch scenarios from catalog
      const catalogRes = await fetch(
        `${apiBaseUrl}/he300/catalog?category=${category}&limit=${numScenarios}&offset=0`
      );
      if (!catalogRes.ok) throw new Error(`Failed to fetch scenarios: ${catalogRes.status}`);
      const catalogData = await catalogRes.json();
      
      if (!catalogData.scenarios || catalogData.scenarios.length === 0) {
        throw new Error('No scenarios found for selected category');
      }

      // Prepare batch request
      const scenarios = catalogData.scenarios.map((s: {
        scenario_id: string;
        category: string;
        input_text: string;
        expected_label: number;
      }) => ({
        scenario_id: s.scenario_id,
        category: s.category,
        input_text: s.input_text,
        expected_label: s.expected_label,
      }));

      // Run batch
      const batchRes = await fetch(`${apiBaseUrl}/he300/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batch_id: batchId || `he300-${Date.now()}`,
          identity_id: identityId,
          guidance_id: guidanceId,
          scenarios: scenarios,
        }),
      });

      if (!batchRes.ok) {
        const errData = await batchRes.json().catch(() => ({}));
        throw new Error(errData.detail || `Batch failed: ${batchRes.status}`);
      }

      const batchResult = await batchRes.json();
      setResult(batchResult);
      
      if (onBenchmarkComplete) {
        onBenchmarkComplete(batchResult);
      }

      // Generate new batch ID for next run
      setBatchId(`he300-${Date.now().toString(36)}`);

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Benchmark failed');
    } finally {
      setRunning(false);
    }
  };

  const categories = catalog?.by_category ? Object.keys(catalog.by_category) : [];
  
  const identities = ['Neutral', 'NIMHs', 'Jiminies', 'Megacricks', 'Agentic_Identity'];
  const guidances = ['Utilitarian', 'Deontological', 'Virtue', 'Fairness', 'Species_Centric', 'Agentic', 'Neutral'];

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-4 py-5 sm:px-6 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-medium text-gray-900">🧪 HE-300 Benchmark Runner</h3>
            <p className="mt-1 text-sm text-gray-500">
              Run ethics benchmarks against {catalog?.total_scenarios?.toLocaleString() || '...'} scenarios
            </p>
          </div>
          {catalog && (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              {Object.entries(catalog.by_category).slice(0, 3).map(([cat, count]) => (
                <span key={cat} className="bg-gray-100 px-2 py-1 rounded">
                  {cat}: {count}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-red-50 border-b border-red-200">
          <p className="text-sm text-red-700">⚠️ {error}</p>
        </div>
      )}

      <form onSubmit={handleRunBenchmark} className="p-4 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {/* Category */}
          <div>
            <label htmlFor="category" className="block text-sm font-medium text-gray-700">
              Category
            </label>
            <select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
            >
              {categories.map((cat) => (
                <option key={cat} value={cat}>
                  {cat} ({catalog?.by_category[cat] || 0} scenarios)
                </option>
              ))}
            </select>
          </div>

          {/* Number of scenarios */}
          <div>
            <label htmlFor="numScenarios" className="block text-sm font-medium text-gray-700">
              Number of Scenarios
            </label>
            <input
              type="number"
              id="numScenarios"
              value={numScenarios}
              onChange={(e) => setNumScenarios(Math.min(50, Math.max(1, parseInt(e.target.value) || 1)))}
              min={1}
              max={50}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
            />
            <p className="mt-1 text-xs text-gray-500">Max 50 per batch</p>
          </div>

          {/* Model (if available) */}
          {models.length > 0 && (
            <div>
              <label htmlFor="model" className="block text-sm font-medium text-gray-700">
                Model
              </label>
              <select
                id="model"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
              >
                {models.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>
          )}

          {/* Identity */}
          <div>
            <label htmlFor="identity" className="block text-sm font-medium text-gray-700">
              Identity Profile
            </label>
            <select
              id="identity"
              value={identityId}
              onChange={(e) => setIdentityId(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
            >
              {identities.map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </div>

          {/* Guidance */}
          <div>
            <label htmlFor="guidance" className="block text-sm font-medium text-gray-700">
              Ethical Guidance
            </label>
            <select
              id="guidance"
              value={guidanceId}
              onChange={(e) => setGuidanceId(e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
            >
              {guidances.map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </div>

          {/* Batch ID */}
          <div>
            <label htmlFor="batchId" className="block text-sm font-medium text-gray-700">
              Batch ID
            </label>
            <input
              type="text"
              id="batchId"
              value={batchId}
              onChange={(e) => setBatchId(e.target.value)}
              placeholder="Auto-generated"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
            />
          </div>
        </div>

        <div className="flex items-center gap-4 pt-4 border-t border-gray-200">
          <button
            type="submit"
            disabled={running || !category}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {running ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Running Benchmark...
              </>
            ) : (
              <>🚀 Run Benchmark</>
            )}
          </button>
          {running && (
            <p className="text-sm text-gray-500">
              Processing {numScenarios} scenarios... This may take a few minutes.
            </p>
          )}
        </div>
      </form>

      {/* Results */}
      {result && (
        <div className="border-t border-gray-200">
          <div className="px-4 py-4 bg-gray-50">
            <h4 className="text-sm font-medium text-gray-900 mb-4">📊 Results: {result.batch_id}</h4>
            
            {/* Summary metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <div className="bg-white p-3 rounded-lg border border-gray-200">
                <p className="text-xs text-gray-500 uppercase">Accuracy</p>
                <p className={`text-2xl font-bold ${
                  result.summary.accuracy >= 0.8 ? 'text-green-600' :
                  result.summary.accuracy >= 0.5 ? 'text-yellow-600' :
                  'text-red-600'
                }`}>
                  {(result.summary.accuracy * 100).toFixed(1)}%
                </p>
              </div>
              <div className="bg-white p-3 rounded-lg border border-gray-200">
                <p className="text-xs text-gray-500 uppercase">Correct</p>
                <p className="text-2xl font-bold text-gray-900">
                  {result.summary.correct}/{result.summary.total}
                </p>
              </div>
              <div className="bg-white p-3 rounded-lg border border-gray-200">
                <p className="text-xs text-gray-500 uppercase">Avg Latency</p>
                <p className="text-2xl font-bold text-gray-900">
                  {result.summary.avg_latency_ms.toFixed(0)}ms
                </p>
              </div>
              <div className="bg-white p-3 rounded-lg border border-gray-200">
                <p className="text-xs text-gray-500 uppercase">Errors</p>
                <p className={`text-2xl font-bold ${result.summary.errors > 0 ? 'text-red-600' : 'text-green-600'}`}>
                  {result.summary.errors}
                </p>
              </div>
            </div>

            {/* Category breakdown */}
            {Object.keys(result.summary.by_category).length > 0 && (
              <div className="mb-4">
                <p className="text-xs text-gray-500 uppercase mb-2">By Category</p>
                <div className="space-y-2">
                  {Object.entries(result.summary.by_category).map(([cat, stats]) => (
                    <div key={cat} className="flex items-center gap-2">
                      <span className="text-sm font-medium w-32">{cat}</span>
                      <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div 
                          className={`h-full transition-all ${
                            stats.accuracy >= 0.8 ? 'bg-green-500' :
                            stats.accuracy >= 0.5 ? 'bg-yellow-500' :
                            'bg-red-500'
                          }`}
                          style={{ width: `${stats.accuracy * 100}%` }}
                        />
                      </div>
                      <span className="text-sm text-gray-600 w-16 text-right">
                        {(stats.accuracy * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Individual results accordion */}
            <details className="bg-white rounded-lg border border-gray-200">
              <summary className="px-4 py-2 cursor-pointer text-sm font-medium text-gray-700 hover:bg-gray-50">
                View {result.results.length} individual results
              </summary>
              <div className="max-h-96 overflow-y-auto divide-y divide-gray-100">
                {result.results.map((r) => (
                  <div key={r.scenario_id} className="px-4 py-3 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-lg ${r.is_correct ? '✅' : '❌'}`} />
                          <code className="text-xs bg-gray-100 px-1 rounded">{r.scenario_id}</code>
                          <span className="text-xs text-gray-500">{r.category}</span>
                        </div>
                        <p className="mt-1 text-gray-600 text-xs line-clamp-2">{r.input_text}</p>
                        {r.model_response && (
                          <p className="mt-1 text-gray-500 text-xs italic line-clamp-2">
                            Response: {r.model_response}
                          </p>
                        )}
                      </div>
                      <div className="text-right text-xs text-gray-500 whitespace-nowrap">
                        <p>Expected: {r.expected_label === 1 ? 'UNETHICAL' : 'ETHICAL'}</p>
                        <p>Got: {r.predicted_label === 1 ? 'UNETHICAL' : 'ETHICAL'}</p>
                        <p>{r.latency_ms.toFixed(0)}ms</p>
                      </div>
                    </div>
                    {r.error && (
                      <p className="mt-1 text-red-600 text-xs">Error: {r.error}</p>
                    )}
                  </div>
                ))}
              </div>
            </details>
          </div>
        </div>
      )}
    </div>
  );
};

export default HE300Runner;
