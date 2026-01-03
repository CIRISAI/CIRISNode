"use client";
import React, { useState, useEffect, useCallback } from 'react';

interface OllamaModel {
  name: string;
  model: string;
  modified_at?: string;
  size?: number;
  digest?: string;
  details?: Record<string, unknown>;
}

interface PullStatus {
  model_name: string;
  status: string;
  progress: string;
}

interface ModelManagerProps {
  apiBaseUrl?: string;
}

const ModelManager: React.FC<ModelManagerProps> = ({ apiBaseUrl = '' }) => {
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pullModelName, setPullModelName] = useState('');
  const [pulling, setPulling] = useState(false);
  const [pullStatus, setPullStatus] = useState<PullStatus | null>(null);
  const [ollamaHealth, setOllamaHealth] = useState<{ status: string; ollama_host: string } | null>(null);

  const fetchModels = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/ollama/models`);
      if (!response.ok) throw new Error(`Failed to fetch models: ${response.status}`);
      const data = await response.json();
      setModels(data.models || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch models');
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  const checkHealth = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/ollama/health`);
      const data = await response.json();
      setOllamaHealth(data);
    } catch {
      setOllamaHealth({ status: 'unhealthy', ollama_host: 'unknown' });
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    fetchModels();
    checkHealth();
  }, [fetchModels, checkHealth]);

  const handlePullModel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pullModelName.trim()) return;

    setPulling(true);
    setPullStatus(null);
    setError(null);

    try {
      const response = await fetch(`${apiBaseUrl}/ollama/models/pull`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_name: pullModelName }),
      });
      
      if (!response.ok) throw new Error(`Failed to start pull: ${response.status}`);
      
      const data = await response.json();
      setPullStatus({ model_name: pullModelName, status: data.status, progress: '0%' });
      
      // Poll for status
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await fetch(`${apiBaseUrl}/ollama/models/pull/status/${encodeURIComponent(pullModelName)}`);
          const statusData = await statusRes.json();
          setPullStatus(statusData);
          
          if (statusData.status === 'completed' || statusData.status === 'error') {
            clearInterval(pollInterval);
            setPulling(false);
            if (statusData.status === 'completed') {
              fetchModels();
              setPullModelName('');
            }
          }
        } catch {
          clearInterval(pollInterval);
          setPulling(false);
        }
      }, 2000);
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to pull model');
      setPulling(false);
    }
  };

  const handleDeleteModel = async (modelName: string) => {
    if (!confirm(`Delete model "${modelName}"? This cannot be undone.`)) return;

    try {
      const response = await fetch(`${apiBaseUrl}/ollama/models/${encodeURIComponent(modelName)}`, {
        method: 'DELETE',
      });
      
      if (!response.ok) throw new Error(`Failed to delete model: ${response.status}`);
      
      fetchModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete model');
    }
  };

  const formatSize = (bytes?: number): string => {
    if (!bytes) return 'Unknown';
    const gb = bytes / (1024 * 1024 * 1024);
    return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
  };

  const popularModels = [
    'gemma3:4b-it-q8_0',
    'qwen2.5:32b',
    'llama3.1:8b',
    'mistral:7b',
    'phi3:medium',
  ];

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-4 py-5 sm:px-6 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-medium text-gray-900">🤖 Model Manager</h3>
            <p className="mt-1 text-sm text-gray-500">Manage Ollama models for HE-300 benchmarks</p>
          </div>
          <div className="flex items-center gap-2">
            {ollamaHealth && (
              <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                ollamaHealth.status === 'healthy' 
                  ? 'bg-green-100 text-green-800' 
                  : 'bg-red-100 text-red-800'
              }`}>
                {ollamaHealth.status === 'healthy' ? '● Connected' : '○ Disconnected'}
              </span>
            )}
            <button
              onClick={() => { fetchModels(); checkHealth(); }}
              disabled={loading}
              className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
            >
              {loading ? 'Loading...' : '↻ Refresh'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-red-50 border-b border-red-200">
          <p className="text-sm text-red-700">⚠️ {error}</p>
        </div>
      )}

      {/* Pull Model Form */}
      <div className="px-4 py-4 bg-gray-50 border-b border-gray-200">
        <form onSubmit={handlePullModel} className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <label htmlFor="modelName" className="sr-only">Model name</label>
            <input
              type="text"
              id="modelName"
              value={pullModelName}
              onChange={(e) => setPullModelName(e.target.value)}
              placeholder="Enter model name (e.g., gemma3:4b-it-q8_0)"
              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
              disabled={pulling}
            />
          </div>
          <button
            type="submit"
            disabled={pulling || !pullModelName.trim()}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {pulling ? '⏳ Pulling...' : '⬇️ Pull Model'}
          </button>
        </form>

        {/* Quick select popular models */}
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="text-xs text-gray-500">Quick select:</span>
          {popularModels.map((model) => (
            <button
              key={model}
              onClick={() => setPullModelName(model)}
              className="inline-flex items-center px-2 py-1 text-xs font-medium rounded bg-gray-200 text-gray-700 hover:bg-gray-300"
            >
              {model}
            </button>
          ))}
        </div>

        {/* Pull status */}
        {pullStatus && (
          <div className="mt-3 p-3 bg-white rounded border border-gray-200">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium">{pullStatus.model_name}</span>
              <span className={`text-xs font-medium ${
                pullStatus.status === 'completed' ? 'text-green-600' :
                pullStatus.status === 'error' ? 'text-red-600' :
                'text-blue-600'
              }`}>
                {pullStatus.status}
              </span>
            </div>
            {pullStatus.status === 'pulling' && (
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div 
                  className="bg-indigo-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: pullStatus.progress || '0%' }}
                />
              </div>
            )}
            <p className="mt-1 text-xs text-gray-500">{pullStatus.progress}</p>
          </div>
        )}
      </div>

      {/* Models list */}
      <div className="divide-y divide-gray-200">
        {models.length === 0 && !loading && (
          <div className="px-4 py-8 text-center text-gray-500">
            <p>No models found. Pull a model to get started.</p>
          </div>
        )}
        
        {models.map((model) => (
          <div key={model.name} className="px-4 py-4 flex items-center justify-between hover:bg-gray-50">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">{model.name}</p>
              <div className="flex items-center gap-4 mt-1">
                <span className="text-xs text-gray-500">
                  Size: {formatSize(model.size)}
                </span>
                {model.modified_at && (
                  <span className="text-xs text-gray-500">
                    Modified: {new Date(model.modified_at).toLocaleDateString()}
                  </span>
                )}
                {model.details?.family ? (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                    {String(model.details.family)}
                  </span>
                ) : null}
              </div>
            </div>
            <div className="flex items-center gap-2 ml-4">
              <button
                onClick={() => handleDeleteModel(model.name)}
                className="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-red-700 bg-red-100 hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
              >
                🗑️ Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ModelManager;
