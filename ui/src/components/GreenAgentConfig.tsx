"use client";

import React, { useState, useEffect, useCallback } from "react";

export interface GreenAgentSettings {
  provider: string;
  model: string;
  apiKey: string;
}

const DEFAULT_SETTINGS: GreenAgentSettings = {
  provider: '',
  model: '',
  apiKey: '',
};

const STORAGE_KEY = 'he300_green_agent_config';

// Provider presets with default models
const PROVIDERS = [
  { id: '', name: 'Server Default', models: [] },
  { id: 'ollama', name: 'Ollama (Local)', models: ['llama3.2', 'qwen3:14b', 'mistral'] },
  { id: 'together', name: 'Together AI', models: ['meta-llama/Llama-3.3-70B-Instruct-Turbo', 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8'] },
  { id: 'openrouter', name: 'OpenRouter', models: ['openai/gpt-4o-mini', 'anthropic/claude-3-haiku', 'meta-llama/llama-4-maverick'] },
  { id: 'openai', name: 'OpenAI', models: ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'] },
  { id: 'anthropic', name: 'Anthropic', models: ['claude-3-haiku-20240307', 'claude-3-sonnet-20240229', 'claude-3-5-sonnet-20241022'] },
];

// Hook to get and set green agent settings from anywhere
export function useGreenAgentSettings() {
  const [settings, setSettings] = useState<GreenAgentSettings>(DEFAULT_SETTINGS);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setSettings(JSON.parse(stored));
      }
    } catch (e) {
      console.error('Failed to load green agent config:', e);
    }
  }, []);

  const updateSettings = useCallback((newSettings: Partial<GreenAgentSettings>) => {
    setSettings(prev => {
      const updated = { ...prev, ...newSettings };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      } catch (e) {
        console.error('Failed to save green agent config:', e);
      }
      return updated;
    });
  }, []);

  return { settings, updateSettings };
}

interface GreenAgentConfigProps {
  apiBaseUrl?: string;
}

export default function GreenAgentConfig({ apiBaseUrl }: GreenAgentConfigProps) {
  const { settings, updateSettings } = useGreenAgentSettings();
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle');
  const [testMessage, setTestMessage] = useState<string>('');

  const API_BASE = apiBaseUrl || process.env.NEXT_PUBLIC_ETHICS_API_URL || "http://localhost:8080";

  const selectedProvider = PROVIDERS.find(p => p.id === settings.provider) || PROVIDERS[0];

  const handleProviderChange = (providerId: string) => {
    const provider = PROVIDERS.find(p => p.id === providerId);
    updateSettings({
      provider: providerId,
      model: provider?.models[0] || '',
    });
  };

  const handleTest = async () => {
    setTestStatus('testing');
    setTestMessage('Testing connection...');

    try {
      // Test by making a simple classification call
      const response = await fetch(`${API_BASE}/he300/test-evaluator`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          test_text: 'I helped someone in need.',
          evaluator_provider: settings.provider || undefined,
          evaluator_model: settings.model || undefined,
          evaluator_api_key: settings.apiKey || undefined,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setTestStatus('success');
        setTestMessage(`Connection successful! Classification: ${data.classification}`);
      } else {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Test failed: ${response.status}`);
      }
    } catch (err) {
      setTestStatus('error');
      setTestMessage(err instanceof Error ? err.message : 'Test failed');
    }
  };

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 bg-green-900/50 rounded-lg">
          <span className="text-2xl">🟢</span>
        </div>
        <div>
          <h3 className="text-lg font-semibold text-white">Green Agent (Evaluator) LLM</h3>
          <p className="text-sm text-gray-400">
            Configure the LLM used for semantic evaluation of benchmark responses
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        {/* Provider */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            Provider
          </label>
          <select
            value={settings.provider}
            onChange={(e) => handleProviderChange(e.target.value)}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-green-500"
          >
            {PROVIDERS.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.name}
              </option>
            ))}
          </select>
        </div>

        {/* Model */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            Model
          </label>
          {selectedProvider.models.length > 0 ? (
            <select
              value={settings.model}
              onChange={(e) => updateSettings({ model: e.target.value })}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-green-500"
            >
              {selectedProvider.models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={settings.model}
              onChange={(e) => updateSettings({ model: e.target.value })}
              placeholder="Server default"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-green-500"
            />
          )}
        </div>

        {/* API Key */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            API Key
          </label>
          <input
            type="password"
            value={settings.apiKey}
            onChange={(e) => updateSettings({ apiKey: e.target.value })}
            placeholder="Uses server ~/.provider_key"
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </div>
      </div>

      {/* Info text */}
      <p className="text-xs text-gray-500 mb-4">
        The green agent performs semantic classification of purple agent responses during benchmarks.
        Leave settings empty to use server environment defaults.
      </p>

      {/* Test Connection */}
      <div className="flex items-center gap-3 pt-4 border-t border-gray-700">
        <button
          onClick={handleTest}
          disabled={testStatus === 'testing'}
          className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:bg-gray-600 text-white rounded-md transition-colors flex items-center gap-2"
        >
          {testStatus === 'testing' ? (
            <>
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
              Testing...
            </>
          ) : (
            <>Test Connection</>
          )}
        </button>

        {testMessage && (
          <span className={`text-sm ${
            testStatus === 'success' ? 'text-green-400' :
            testStatus === 'error' ? 'text-red-400' :
            'text-gray-400'
          }`}>
            {testMessage}
          </span>
        )}
      </div>

      {/* Current Config Display */}
      <div className="mt-4 pt-4 border-t border-gray-700">
        <h4 className="text-sm font-medium text-gray-300 mb-2">Current Configuration</h4>
        <div className="bg-gray-900 rounded-md p-3 font-mono text-xs text-gray-300">
          <div>
            <span className="text-blue-400">provider:</span>{' '}
            <span className="text-green-400">{settings.provider || '(server default)'}</span>
          </div>
          <div>
            <span className="text-blue-400">model:</span>{' '}
            <span className="text-green-400">{settings.model || '(server default)'}</span>
          </div>
          <div>
            <span className="text-blue-400">api_key:</span>{' '}
            <span className="text-yellow-400">{settings.apiKey ? '********' : '(server default)'}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
