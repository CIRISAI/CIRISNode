"use client";
import React, { useState, useEffect } from 'react';

const APIKeyManager: React.FC = () => {
  const [apiKeys, setApiKeys] = useState({
    openAI: '', xAI: '', gemini: '', ollama: '', anthropic: '', mistral: ''
  });
  const [keysSaved, setKeysSaved] = useState<boolean>(false);
  const [keysError, setKeysError] = useState<string | null>(null);

  const [username, setUsername] = useState<string>('testuser');
  const [password, setPassword] = useState<string>('testpass');
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tokenSuccess, setTokenSuccess] = useState<boolean>(false);

  useEffect(() => {
    const savedApiKeys = localStorage.getItem('apiKeys');
    if (savedApiKeys) setApiKeys(JSON.parse(savedApiKeys));
    const savedAuthToken = localStorage.getItem('authToken');
    if (savedAuthToken) setAuthToken(savedAuthToken);
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>, service: string) => {
    const { value } = e.target;
    setApiKeys(prev => ({ ...prev, [service]: value }));
    setKeysSaved(false);
  };

  const handleSaveKeys = () => {
    try {
      localStorage.setItem('apiKeys', JSON.stringify(apiKeys));
      setKeysSaved(true);
      setKeysError(null);
      setTimeout(() => setKeysSaved(false), 3000);
    } catch (err) {
      setKeysError(err instanceof Error ? err.message : 'An unknown error occurred');
      setKeysSaved(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError(null);
    setTokenSuccess(false);
    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);

      // The UI calls /api/v1/auth/token. This will be proxied by Next.js
      // to /api/v1/auth/token (backend API service), proxied by Next.js
      const fetchUrl = process.env.NEXT_PUBLIC_API_BASE_URL
        ? `${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/auth/token`
        : '/api/v1/auth/token'; 
      
      const response = await fetch(fetchUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData.toString(),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Login failed due to network or server error' }));
        throw new Error(`HTTP error! status: ${response.status} - ${errorData.detail}`);
      }
      const data = await response.json();
      if (data.access_token) {
        localStorage.setItem('authToken', data.access_token);
        setAuthToken(data.access_token);
        setTokenSuccess(true);
        setTimeout(() => setTokenSuccess(false), 3000);
      } else {
        throw new Error("Access token not found in response.");
      }
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'An unknown error occurred during login');
      localStorage.removeItem('authToken');
      setAuthToken(null);
    }
  };

  return (
    <div className="bg-white shadow overflow-hidden sm:rounded-lg mt-6">
      <div className="px-4 py-5 sm:px-6">
        <h3 className="text-lg leading-6 font-medium text-gray-900">Authentication & API Keys</h3>
        <p className="mt-1 max-w-2xl text-sm text-gray-500">Manage CIRISNode JWT and external service API keys.</p>
      </div>
      <div className="border-t border-gray-200 divide-y divide-gray-200">
        {/* CIRISNode Auth Section */}
        <div className="px-4 py-5 sm:p-6">
          <h4 className="text-md font-semibold text-gray-700 mb-2">CIRISNode Authentication</h4>
          {authToken ? (
            <div>
              <p className="text-sm text-green-600">Authenticated. Token stored in localStorage.</p>
              <button 
                onClick={() => { localStorage.removeItem('authToken'); setAuthToken(null); }}
                className="mt-2 text-sm text-indigo-600 hover:text-indigo-500"
              >
                Logout
              </button>
            </div>
          ) : (
            <form onSubmit={handleLogin}>
              <div className="grid grid-cols-1 gap-y-6 gap-x-4 sm:grid-cols-6">
                <div className="sm:col-span-3">
                  <label htmlFor="username" className="block text-sm font-medium text-gray-700">Username</label>
                  <input type="text" name="username" id="username" value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 block w-full rounded-md border-gray-300 shadow-sm sm:text-sm" />
                </div>
                <div className="sm:col-span-3">
                  <label htmlFor="password"className="block text-sm font-medium text-gray-700">Password</label>
                  <input type="password" name="password" id="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 block w-full rounded-md border-gray-300 shadow-sm sm:text-sm" />
                </div>
              </div>
              <button type="submit" className="mt-4 inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700">
                Login & Get Token
              </button>
              {tokenSuccess && <p className="mt-2 text-sm text-green-600">Token obtained and stored!</p>}
              {authError && <p className="mt-2 text-sm text-red-600">Error: {authError}</p>}
            </form>
          )}
        </div>

        {/* External API Keys Section */}
        <div className="px-4 py-5 sm:p-6">
          <h4 className="text-md font-semibold text-gray-700 mb-2">External Service API Keys</h4>
           <p className="text-xs text-gray-500 mb-3">(Keys are stored in localStorage for this demo - NOT SECURE FOR PRODUCTION)</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label htmlFor="openAI" className="block text-sm font-medium text-gray-700">OpenAI API Key</label>
              <input type="password" id="openAI" value={apiKeys.openAI} onChange={(e) => handleInputChange(e, 'openAI')} className="mt-1 block w-full rounded-md border-gray-300 shadow-sm sm:text-sm" placeholder="Enter your OpenAI API key" />
            </div>
            <div>
              <label htmlFor="xAI" className="block text-sm font-medium text-gray-700">xAI API Key</label>
              <input type="password" id="xAI" value={apiKeys.xAI} onChange={(e) => handleInputChange(e, 'xAI')} className="mt-1 block w-full rounded-md border-gray-300 shadow-sm sm:text-sm" placeholder="Enter your xAI API key" />
            </div>
            <div>
              <label htmlFor="gemini" className="block text-sm font-medium text-gray-700">Gemini API Key</label>
              <input type="password" id="gemini" value={apiKeys.gemini} onChange={(e) => handleInputChange(e, 'gemini')} className="mt-1 block w-full rounded-md border-gray-300 shadow-sm sm:text-sm" placeholder="Enter your Gemini API key" />
            </div>
            <div>
              <label htmlFor="ollama" className="block text-sm font-medium text-gray-700">Ollama API Key/URL</label>
              <input type="text" id="ollama" value={apiKeys.ollama} onChange={(e) => handleInputChange(e, 'ollama')} className="mt-1 block w-full rounded-md border-gray-300 shadow-sm sm:text-sm" placeholder="Enter your Ollama API key or Base URL" />
            </div>
            <div>
              <label htmlFor="anthropic" className="block text-sm font-medium text-gray-700">Anthropic API Key</label>
              <input type="password" id="anthropic" value={apiKeys.anthropic} onChange={(e) => handleInputChange(e, 'anthropic')} className="mt-1 block w-full rounded-md border-gray-300 shadow-sm sm:text-sm" placeholder="Enter your Anthropic API key" />
            </div>
            <div>
              <label htmlFor="mistral" className="block text-sm font-medium text-gray-700">Mistral API Key</label>
              <input type="password" id="mistral" value={apiKeys.mistral} onChange={(e) => handleInputChange(e, 'mistral')} className="mt-1 block w-full rounded-md border-gray-300 shadow-sm sm:text-sm" placeholder="Enter your Mistral API key" />
            </div>
          </div>
          <div className="mt-6">
            <button onClick={handleSaveKeys} className="inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700">
              Save External API Keys
            </button>
          </div>
          {keysSaved && <p className="mt-2 text-sm text-green-600">External API keys saved to localStorage.</p>}
          {keysError && <p className="mt-2 text-sm text-red-600">Error saving keys: {keysError}</p>}
        </div>
      </div>
    </div>
  );
};

export default APIKeyManager;
