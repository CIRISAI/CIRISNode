"use client";
import React, { useState, useEffect } from 'react'; // Combined imports
import axios from 'axios';

const TestConnection = () => {
  const [provider, setProvider] = useState('openai');
  const [apiKey, setApiKey] = useState('');
  const [ollamaModels, setOllamaModels] = useState([]);
  const [selectedOllamaModel, setSelectedOllamaModel] = useState('');
  const [response, setResponse] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);

  useEffect(() => {
    if (provider === 'ollama') {
      const fetchOllamaModels = async () => {
        setLoadingModels(true);
        setError(null); // Clear previous errors
        try {
          const ollamaBaseUrl = process.env.NEXT_PUBLIC_OLLAMA_BASE_URL || 'http://localhost:11434';
          const res = await axios.get(`${ollamaBaseUrl}/api/tags`);
          if (res.data?.models?.length > 0) {
            setOllamaModels(res.data.models);
            setSelectedOllamaModel(res.data.models[0]);
          } else {
            setOllamaModels([]);
            setSelectedOllamaModel('');
            setError('No models available. Ensure Ollama is running with models installed.');
          }
        } catch (err) {
          setError('Failed to fetch Ollama models: ' + (err.response?.data?.detail || err.message));
          setOllamaModels([]);
          setSelectedOllamaModel('');
        } finally {
          setLoadingModels(false);
        }
      };
      fetchOllamaModels();
    } else {
      setOllamaModels([]); // Clear Ollama models if another provider is selected
      setSelectedOllamaModel('');
    }
  }, [provider]); // Re-fetch models when provider changes to Ollama

  const handleTestConnection = async () => {
    if (provider === 'openai' && !apiKey) {
      setError('Please enter an API key for OpenAI.');
      return;
    }
    if (provider === 'ollama' && !selectedOllamaModel) {
      setError('Please select an Ollama model.');
      return;
    }

    setLoading(true);
    setError(null);
    setResponse(null);

const requestBody = {
  provider,
  prompt: "Hi, can you confirm you are operational?",
  ...(provider === 'openai' && { apiKey }), // Only include apiKey for OpenAI
        model: provider === 'ollama' ? (typeof selectedOllamaModel === 'string' ? selectedOllamaModel : selectedOllamaModel.name) : (provider === 'openai' ? 'gpt-3.5-turbo' : undefined)
};

    try {
      const res = await axios.post(`/api/v1/test-llm`, requestBody);
      setResponse(res.data.message); // Display raw LLM response
    } catch (error) {
      setError('Failed to connect to LLM: ' + (error.response?.data?.detail || error.message));
      setResponse(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ 
        margin: '20px auto', 
        padding: '20px', 
        border: '1px solid #333', 
        borderRadius: '8px', 
        maxWidth: '500px', 
        backgroundColor: '#f9f9f9',
        boxShadow: '0 2px 4px rgba(0,0,0,0.1)' 
    }}>
      <h2 style={{ textAlign: 'center', color: '#333', marginBottom: '20px' }}>Test LLM Connection</h2>
      
      <div style={{ marginBottom: '15px' }}>
        <label htmlFor="provider" style={{ marginRight: '10px', color: '#555', display: 'block', marginBottom: '5px' }}>
          LLM Provider:
        </label>
        <select
          id="provider"
          value={provider}
          onChange={(e) => {
            setProvider(e.target.value);
            setApiKey(''); // Clear API key when provider changes
            setError(null); // Clear errors
            setResponse(null); // Clear previous response
          }}
          style={{ padding: '8px', width: '100%', borderRadius: '4px', border: '1px solid #ccc' }}
        >
          <option value="openai">OpenAI</option>
          <option value="ollama">Ollama (Local)</option>
        </select>
      </div>

      {provider === 'openai' && (
        <div style={{ marginBottom: '15px' }}>
          <label htmlFor="apiKey" style={{ marginRight: '10px', color: '#555', display: 'block', marginBottom: '5px' }}>
            OpenAI API Key:
          </label>
          <input
            type="password"
            id="apiKey"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Enter your OpenAI API Key"
            style={{ padding: '8px', width: '100%', borderRadius: '4px', border: '1px solid #ccc' }}
          />
        </div>
      )}

      {provider === 'ollama' && (
        <div style={{ marginBottom: '15px' }}>
          <label htmlFor="ollamaModel" style={{ marginRight: '10px', color: '#555', display: 'block', marginBottom: '5px' }}>
            Ollama Model:
          </label>
          {loadingModels ? (
            <p>Loading Ollama models...</p>
          ) : ollamaModels.length > 0 ? (
            <select
              id="ollamaModel"
              value={selectedOllamaModel}
              onChange={(e) => setSelectedOllamaModel(e.target.value)}
              style={{ padding: '8px', width: '100%', borderRadius: '4px', border: '1px solid #ccc' }}
            >
              {ollamaModels.map((modelName) => (
                <option key={modelName} value={modelName}>{modelName}</option>
              ))}
            </select>
          ) : (
            <p style={{color: 'orange'}}>No Ollama models found or failed to load. Ensure Ollama is running and accessible.</p>
          )}
        </div>
      )}
      
      <button 
        onClick={handleTestConnection} 
        style={{ 
          padding: '10px 15px', 
          marginBottom: '15px', 
          backgroundColor: loading ? '#ccc' : '#007bff', 
          color: 'white', 
          border: 'none', 
          borderRadius: '4px', 
          cursor: loading ? 'not-allowed' : 'pointer',
          width: '100%',
          fontSize: '16px'
        }}
        disabled={loading || (provider === 'openai' && !apiKey) || (provider === 'ollama' && !selectedOllamaModel)}
      >
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{
              border: '2px solid #f3f3f3',
              borderTop: '2px solid #3498db',
              borderRadius: '50%',
              width: '16px',
              height: '16px',
              animation: 'spin 1s linear infinite',
              marginRight: '10px'
            }}></div>
            Testing...
            <style>{`
              @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
              }
            `}</style>
          </div>
        ) : `Test ${provider.charAt(0).toUpperCase() + provider.slice(1)} Connection`}
      </button>
      
      {response && (
        <div style={{ marginTop: '15px', padding: '10px', backgroundColor: '#e6fffa', border: '1px solid #38a169', borderRadius: '4px' }}>
          <h4 style={{ color: '#2f855a', marginBottom: '5px' }}>LLM Response:</h4>
          <p style={{ color: '#2f855a', whiteSpace: 'pre-wrap' }}>{response}</p>
        </div>
      )}
      {error && (
        <div style={{ marginTop: '15px', padding: '10px', backgroundColor: '#ffebee', border: '1px solid #e53e3e', borderRadius: '4px' }}>
          <h4 style={{ color: '#c53030', marginBottom: '5px' }}>Error:</h4>
          <p style={{ color: '#c53030' }}>{error}</p>
        </div>
      )}
    </div>
  );
};

export default TestConnection;
