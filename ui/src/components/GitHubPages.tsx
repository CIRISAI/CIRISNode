"use client";
import React, { useState, useEffect, useCallback } from 'react';

interface GitHubConfig {
  configured: boolean;
  repo_full_name?: string;
  target_branch?: string;
  target_path?: string;
  token_preview?: string;
}

interface GitHubRepo {
  full_name: string;
  name: string;
  owner: string;
  description?: string;
  private: boolean;
  default_branch: string;
  html_url: string;
  has_pages: boolean;
  pages_url?: string;
  permissions: Record<string, boolean>;
}

interface ReportMetadata {
  report_id: string;
  batch_id: string;
  model_name?: string;
  accuracy?: number;
  format: string;
  created_at: string;
  file_path: string;
  file_size: number;
}

interface PublishedReport {
  report_id: string;
  batch_id: string;
  model_name: string;
  format: string;
  accuracy: number;
  published_at: string;
  pages_url: string;
  raw_url: string;
  file_name: string;
}

interface DeploymentResult {
  status: string;
  deployed_reports: string[];
  failed_reports: Array<{ report_id: string; error: string }>;
  pages_url?: string;
  index_url?: string;
}

interface GitHubPagesProps {
  apiBaseUrl?: string;
}

const GitHubPages: React.FC<GitHubPagesProps> = ({ apiBaseUrl = '' }) => {
  // Config state
  const [config, setConfig] = useState<GitHubConfig | null>(null);
  const [configLoading, setConfigLoading] = useState(true);
  const [showConfigForm, setShowConfigForm] = useState(false);
  
  // Form state
  const [token, setToken] = useState('');
  const [selectedRepo, setSelectedRepo] = useState('');
  const [targetBranch, setTargetBranch] = useState('gh-pages');
  const [targetPath, setTargetPath] = useState('reports');
  
  // Repos state
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [reposLoading, setReposLoading] = useState(false);
  
  // Reports state
  const [localReports, setLocalReports] = useState<ReportMetadata[]>([]);
  const [publishedReports, setPublishedReports] = useState<PublishedReport[]>([]);
  const [selectedReports, setSelectedReports] = useState<Set<string>>(new Set());
  
  // Deployment state
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<DeploymentResult | null>(null);
  
  // UI state
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'deploy' | 'published'>('deploy');

  // Fetch GitHub config on mount
  const fetchConfig = useCallback(async () => {
    setConfigLoading(true);
    try {
      const response = await fetch(`${apiBaseUrl}/github/config`);
      if (response.ok) {
        const data = await response.json();
        setConfig(data);
        if (!data.configured) {
          setShowConfigForm(true);
        }
      }
    } catch {
      console.error('Failed to fetch config');
    } finally {
      setConfigLoading(false);
    }
  }, [apiBaseUrl]);

  // Fetch repos when token is entered
  const fetchRepos = useCallback(async (tokenValue: string) => {
    if (!tokenValue || tokenValue.length < 10) return;
    
    setReposLoading(true);
    try {
      // Temporarily save config to test token
      const response = await fetch(`${apiBaseUrl}/github/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: tokenValue,
          repo_full_name: selectedRepo || 'test/test',
          target_branch: targetBranch,
          target_path: targetPath,
        }),
      });
      
      if (response.ok) {
        // Now fetch repos
        const reposResponse = await fetch(`${apiBaseUrl}/github/repos`);
        if (reposResponse.ok) {
          const data = await reposResponse.json();
          setRepos(data);
        }
      }
    } catch {
      console.error('Failed to fetch repos');
    } finally {
      setReposLoading(false);
    }
  }, [apiBaseUrl, selectedRepo, targetBranch, targetPath]);

  // Fetch local reports
  const fetchLocalReports = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/reports/`);
      if (response.ok) {
        const data = await response.json();
        setLocalReports(data.reports || []);
      }
    } catch {
      console.error('Failed to fetch reports');
    }
  }, [apiBaseUrl]);

  // Fetch published reports
  const fetchPublishedReports = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/github/published`);
      if (response.ok) {
        const data = await response.json();
        setPublishedReports(data.reports || []);
      }
    } catch {
      console.error('Failed to fetch published reports');
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    fetchConfig();
    fetchLocalReports();
  }, [fetchConfig, fetchLocalReports]);

  useEffect(() => {
    if (config?.configured) {
      fetchPublishedReports();
    }
  }, [config, fetchPublishedReports]);

  // Save configuration
  const handleSaveConfig = async () => {
    if (!token || !selectedRepo) {
      setError('Please enter a GitHub token and select a repository');
      return;
    }

    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/github/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token,
          repo_full_name: selectedRepo,
          target_branch: targetBranch,
          target_path: targetPath,
          auto_enable_pages: true,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to save configuration');
      }

      const result = await response.json();
      setSuccess(`Connected to ${selectedRepo} as ${result.user}`);
      setShowConfigForm(false);
      fetchConfig();
      
      // Enable Pages if not already enabled
      if (!result.has_pages) {
        const [owner, repo] = selectedRepo.split('/');
        await fetch(`${apiBaseUrl}/github/repo/${owner}/${repo}/enable-pages?branch=${targetBranch}`, {
          method: 'POST',
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Configuration failed');
    }
  };

  // Clear configuration
  const handleClearConfig = async () => {
    if (!confirm('Clear GitHub configuration?')) return;
    
    try {
      await fetch(`${apiBaseUrl}/github/config`, { method: 'DELETE' });
      setConfig(null);
      setShowConfigForm(true);
      setToken('');
      setSelectedRepo('');
      setRepos([]);
      setPublishedReports([]);
    } catch {
      setError('Failed to clear configuration');
    }
  };

  // Toggle report selection
  const toggleReport = (reportId: string) => {
    const newSelected = new Set(selectedReports);
    if (newSelected.has(reportId)) {
      newSelected.delete(reportId);
    } else {
      newSelected.add(reportId);
    }
    setSelectedReports(newSelected);
  };

  // Select all reports
  const selectAllReports = () => {
    setSelectedReports(new Set(localReports.map(r => r.report_id)));
  };

  // Clear selection
  const clearSelection = () => {
    setSelectedReports(new Set());
  };

  // Deploy selected reports
  const handleDeploy = async () => {
    if (selectedReports.size === 0) {
      setError('Please select at least one report to deploy');
      return;
    }

    setDeploying(true);
    setError(null);
    setDeployResult(null);

    try {
      const response = await fetch(`${apiBaseUrl}/github/deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          report_ids: Array.from(selectedReports),
          generate_index: true,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Deployment failed');
      }

      const result: DeploymentResult = await response.json();
      setDeployResult(result);

      if (result.deployed_reports.length > 0) {
        setSuccess(`Successfully deployed ${result.deployed_reports.length} report(s) to GitHub Pages`);
        setSelectedReports(new Set());
        fetchPublishedReports();
      }

      if (result.failed_reports.length > 0) {
        setError(`${result.failed_reports.length} report(s) failed to deploy`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Deployment failed');
    } finally {
      setDeploying(false);
    }
  };

  // Unpublish a report
  const handleUnpublish = async (reportId: string) => {
    if (!confirm(`Remove report ${reportId} from GitHub Pages?`)) return;

    try {
      const response = await fetch(`${apiBaseUrl}/github/published/${reportId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error('Failed to unpublish report');
      }

      setSuccess(`Report ${reportId} removed from GitHub Pages`);
      fetchPublishedReports();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unpublish failed');
    }
  };

  const formatDate = (iso: string): string => {
    return new Date(iso).toLocaleString();
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (configLoading) {
    return (
      <div className="bg-white shadow rounded-lg p-8 text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mx-auto"></div>
        <p className="mt-4 text-gray-600">Loading GitHub configuration...</p>
      </div>
    );
  }

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-4 py-5 sm:px-6 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-medium text-gray-900">🚀 GitHub Pages Deployment</h3>
            <p className="mt-1 text-sm text-gray-500">
              Publish benchmark reports to GitHub Pages for public viewing
            </p>
          </div>
          {config?.configured && (
            <div className="flex items-center gap-4">
              <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800">
                ✓ Connected to {config.repo_full_name}
              </span>
              <button
                onClick={handleClearConfig}
                className="text-sm text-gray-500 hover:text-red-600"
              >
                Disconnect
              </button>
            </div>
          )}
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

      {/* Configuration Form */}
      {showConfigForm && (
        <div className="p-4 bg-gray-50 border-b border-gray-200">
          <h4 className="text-sm font-medium text-gray-900 mb-4">Configure GitHub Connection</h4>
          
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                GitHub Personal Access Token
                <span className="ml-1 text-gray-400 font-normal">
                  (requires repo scope)
                </span>
              </label>
              <input
                type="password"
                value={token}
                onChange={(e) => {
                  setToken(e.target.value);
                  if (e.target.value.length >= 40) {
                    fetchRepos(e.target.value);
                  }
                }}
                placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
              />
              <p className="mt-1 text-xs text-gray-500">
                Create a token at GitHub → Settings → Developer settings → Personal access tokens
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Repository</label>
              {reposLoading ? (
                <div className="mt-1 text-sm text-gray-500">Loading repositories...</div>
              ) : repos.length > 0 ? (
                <select
                  value={selectedRepo}
                  onChange={(e) => setSelectedRepo(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                >
                  <option value="">Select a repository...</option>
                  {repos.filter(r => r.permissions.push).map((repo) => (
                    <option key={repo.full_name} value={repo.full_name}>
                      {repo.full_name} {repo.private ? '🔒' : ''} {repo.has_pages ? '📄' : ''}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={selectedRepo}
                  onChange={(e) => setSelectedRepo(e.target.value)}
                  placeholder="owner/repository"
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                />
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">Branch</label>
                <input
                  type="text"
                  value={targetBranch}
                  onChange={(e) => setTargetBranch(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Path</label>
                <input
                  type="text"
                  value={targetPath}
                  onChange={(e) => setTargetPath(e.target.value)}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                />
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleSaveConfig}
                disabled={!token || !selectedRepo}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Connect to GitHub
              </button>
              {config?.configured && (
                <button
                  onClick={() => setShowConfigForm(false)}
                  className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Main Content - Only show when configured */}
      {config?.configured && !showConfigForm && (
        <>
          {/* Tabs */}
          <div className="border-b border-gray-200">
            <nav className="flex -mb-px">
              <button
                onClick={() => setActiveTab('deploy')}
                className={`px-6 py-3 text-sm font-medium border-b-2 ${
                  activeTab === 'deploy'
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                📤 Deploy Reports
              </button>
              <button
                onClick={() => setActiveTab('published')}
                className={`px-6 py-3 text-sm font-medium border-b-2 ${
                  activeTab === 'published'
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                🌐 Published Reports ({publishedReports.length})
              </button>
            </nav>
          </div>

          {/* Deploy Tab */}
          {activeTab === 'deploy' && (
            <div className="p-4">
              {/* Deployment Actions */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <button
                    onClick={selectAllReports}
                    className="text-sm text-indigo-600 hover:text-indigo-800"
                  >
                    Select All
                  </button>
                  <span className="text-gray-300">|</span>
                  <button
                    onClick={clearSelection}
                    className="text-sm text-gray-600 hover:text-gray-800"
                  >
                    Clear
                  </button>
                  <span className="ml-4 text-sm text-gray-500">
                    {selectedReports.size} of {localReports.length} selected
                  </span>
                </div>
                <button
                  onClick={handleDeploy}
                  disabled={deploying || selectedReports.size === 0}
                  className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {deploying ? (
                    <>
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Deploying...
                    </>
                  ) : (
                    <>🚀 Deploy to GitHub Pages</>
                  )}
                </button>
              </div>

              {/* Deployment Result */}
              {deployResult && (
                <div className={`mb-4 p-4 rounded-lg border ${
                  deployResult.status === 'success' ? 'bg-green-50 border-green-200' : 'bg-yellow-50 border-yellow-200'
                }`}>
                  <h5 className="font-medium mb-2">Deployment Complete</h5>
                  {deployResult.deployed_reports.length > 0 && (
                    <p className="text-sm text-green-700">
                      ✅ Deployed: {deployResult.deployed_reports.join(', ')}
                    </p>
                  )}
                  {deployResult.failed_reports.length > 0 && (
                    <p className="text-sm text-red-700 mt-1">
                      ❌ Failed: {deployResult.failed_reports.map(f => `${f.report_id} (${f.error})`).join(', ')}
                    </p>
                  )}
                  {deployResult.index_url && (
                    <p className="text-sm mt-2">
                      📄 View reports at: <a href={deployResult.index_url} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">{deployResult.index_url}</a>
                    </p>
                  )}
                </div>
              )}

              {/* Local Reports List */}
              <div className="divide-y divide-gray-200 border border-gray-200 rounded-lg">
                {localReports.length === 0 ? (
                  <div className="p-8 text-center text-gray-500">
                    <p>No reports available.</p>
                    <p className="text-sm mt-1">Generate reports from the Report Generator tab first.</p>
                  </div>
                ) : (
                  localReports.map((report) => {
                    const isPublished = publishedReports.some(p => p.report_id === report.report_id);
                    const isSelected = selectedReports.has(report.report_id);
                    
                    return (
                      <div
                        key={report.report_id}
                        className={`px-4 py-3 flex items-center gap-4 hover:bg-gray-50 ${
                          isSelected ? 'bg-indigo-50' : ''
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleReport(report.report_id)}
                          className="h-4 w-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-lg">
                              {report.format === 'markdown' ? '📝' : report.format === 'html' ? '🌐' : '📊'}
                            </span>
                            <code className="text-sm font-medium text-gray-900">{report.report_id}</code>
                            {isPublished && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                                ✓ Published
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-4 mt-1 text-xs text-gray-500">
                            {report.model_name && (
                              <span className="font-medium text-indigo-600">🤖 {report.model_name}</span>
                            )}
                            <span>Batch: {report.batch_id}</span>
                            <span>Format: {report.format}</span>
                            <span>Size: {formatSize(report.file_size)}</span>
                            <span>Created: {formatDate(report.created_at)}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}

          {/* Published Tab */}
          {activeTab === 'published' && (
            <div className="p-4">
              {/* Public URL Banner */}
              {publishedReports.length > 0 && (
                <div className="mb-4 p-4 bg-indigo-50 rounded-lg border border-indigo-200">
                  <div className="flex items-center justify-between">
                    <div>
                      <h5 className="font-medium text-indigo-900">📄 Public Reports Index</h5>
                      <p className="text-sm text-indigo-700 mt-1">
                        Anyone can view your published reports at this URL:
                      </p>
                      <a
                        href={`https://${config.repo_full_name?.split('/')[0]}.github.io/${config.repo_full_name?.split('/')[1]}/${config.target_path}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-indigo-600 hover:underline font-medium"
                      >
                        {`https://${config.repo_full_name?.split('/')[0]}.github.io/${config.repo_full_name?.split('/')[1]}/${config.target_path}/`}
                      </a>
                    </div>
                    <button
                      onClick={() => {
                        const url = `https://${config.repo_full_name?.split('/')[0]}.github.io/${config.repo_full_name?.split('/')[1]}/${config.target_path}/`;
                        navigator.clipboard.writeText(url);
                        setSuccess('URL copied to clipboard!');
                      }}
                      className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700"
                    >
                      📋 Copy URL
                    </button>
                  </div>
                </div>
              )}

              {/* Published Reports Grid */}
              {publishedReports.length === 0 ? (
                <div className="p-8 text-center text-gray-500">
                  <p>No reports published yet.</p>
                  <p className="text-sm mt-1">Deploy reports from the Deploy tab to make them publicly available.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {publishedReports.map((report) => (
                    <div
                      key={report.report_id}
                      className="border border-gray-200 rounded-lg overflow-hidden hover:shadow-md transition-shadow"
                    >
                      <div className="px-4 py-3 bg-gradient-to-r from-indigo-500 to-purple-600 text-white">
                        <h5 className="font-medium truncate">📊 {report.batch_id}</h5>
                        <p className="text-sm opacity-90">🤖 {report.model_name}</p>
                      </div>
                      <div className="px-4 py-3">
                        <div className="text-center mb-3">
                          <span className={`text-3xl font-bold ${
                            report.accuracy >= 0.8 ? 'text-green-600' :
                            report.accuracy >= 0.5 ? 'text-yellow-600' : 'text-red-600'
                          }`}>
                            {(report.accuracy * 100).toFixed(1)}%
                          </span>
                          <p className="text-xs text-gray-500">Accuracy</p>
                        </div>
                        <div className="flex flex-wrap gap-2 mb-3 justify-center">
                          <span className="px-2 py-0.5 bg-gray-100 rounded text-xs text-gray-600">
                            {report.format.toUpperCase()}
                          </span>
                          <span className="px-2 py-0.5 bg-gray-100 rounded text-xs text-gray-600">
                            {new Date(report.published_at).toLocaleDateString()}
                          </span>
                        </div>
                        <div className="flex gap-2">
                          <a
                            href={report.pages_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex-1 text-center px-3 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700"
                          >
                            View
                          </a>
                          <a
                            href={report.raw_url}
                            download
                            className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50"
                          >
                            ⬇️
                          </a>
                          <button
                            onClick={() => handleUnpublish(report.report_id)}
                            className="px-3 py-1.5 text-sm text-red-600 border border-red-300 rounded hover:bg-red-50"
                          >
                            🗑️
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Instructions */}
      <div className="px-4 py-4 bg-gray-50 border-t border-gray-200">
        <details>
          <summary className="text-sm font-medium text-gray-700 cursor-pointer hover:text-gray-900">
            📚 How GitHub Pages deployment works
          </summary>
          <div className="mt-3 prose prose-sm text-gray-600">
            <ol className="list-decimal list-inside space-y-2">
              <li>Create a GitHub Personal Access Token with <code>repo</code> scope</li>
              <li>Connect this tool to your GitHub repository</li>
              <li>Select reports to publish from the local reports list</li>
              <li>Click &quot;Deploy to GitHub Pages&quot; to publish</li>
              <li>Reports will be available at your GitHub Pages URL</li>
            </ol>
            <div className="mt-3 p-3 bg-white rounded border border-gray-200">
              <p className="text-xs font-medium text-gray-700 mb-2">🔐 Security Note:</p>
              <p className="text-xs text-gray-600">
                Your GitHub token is stored locally and only used for deployment. 
                For production use, consider using a fine-grained token with minimal permissions.
              </p>
            </div>
          </div>
        </details>
      </div>
    </div>
  );
};

export default GitHubPages;
