"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "../lib/api";

interface TrendInfo {
  prev_accuracy: number;
  delta: number;
  direction: "up" | "down" | "stable";
}

interface ScoreEntry {
  model_id: string;
  display_name: string;
  provider: string;
  accuracy: number | null;
  total_scenarios: number;
  categories: Record<string, { correct: number; total: number; accuracy: number }> | null;
  badges: string[];
  avg_latency_ms: number | null;
  completed_at: string | null;
  trend: TrendInfo | null;
}

interface LeaderboardEntry {
  rank: number;
  agent_name: string;
  target_model: string;
  accuracy: number | null;
  badges: string[];
  completed_at: string | null;
}

export default function ScoresPage() {
  const [scores, setScores] = useState<ScoreEntry[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedModel, setExpandedModel] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [scoresRes, lbRes] = await Promise.all([
        apiFetch<{ scores: ScoreEntry[] }>("/api/v1/scores"),
        apiFetch<{ entries: LeaderboardEntry[] }>("/api/v1/leaderboard"),
      ]);
      setScores(scoresRes.scores || []);
      setLeaderboard(lbRes.entries || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load scores");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const trendArrow = (trend: TrendInfo | null) => {
    if (!trend) return null;
    if (trend.direction === "up") return <span className="text-green-600">+{(trend.delta * 100).toFixed(1)}%</span>;
    if (trend.direction === "down") return <span className="text-red-600">{(trend.delta * 100).toFixed(1)}%</span>;
    return <span className="text-gray-400">-</span>;
  };

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading scores...</div>;
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Frontier Scores */}
      <section>
        <h2 className="text-xl font-bold text-gray-900 mb-4">Frontier Model Scores</h2>
        {scores.length === 0 ? (
          <p className="text-gray-500">No frontier scores available yet.</p>
        ) : (
          <div className="bg-white shadow rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Rank</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Provider</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Accuracy</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Scenarios</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Badges</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Trend</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Evaluated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {scores.map((s, idx) => (
                  <>
                    <tr
                      key={s.model_id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() =>
                        setExpandedModel(expandedModel === s.model_id ? null : s.model_id)
                      }
                    >
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{idx + 1}</td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{s.display_name}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">{s.provider}</td>
                      <td className="px-4 py-3 text-sm text-right font-mono">
                        {s.accuracy != null ? `${(s.accuracy * 100).toFixed(1)}%` : "-"}
                      </td>
                      <td className="px-4 py-3 text-sm text-right">{s.total_scenarios}</td>
                      <td className="px-4 py-3 text-sm">
                        <div className="flex gap-1 flex-wrap">
                          {s.badges.map((b) => (
                            <span
                              key={b}
                              className="inline-block bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded"
                            >
                              {b}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm text-right">{trendArrow(s.trend)}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {s.completed_at ? new Date(s.completed_at).toLocaleDateString() : "-"}
                      </td>
                    </tr>
                    {expandedModel === s.model_id && s.categories && (
                      <tr key={`${s.model_id}-detail`}>
                        <td colSpan={8} className="px-4 py-3 bg-gray-50">
                          <div className="text-sm font-medium text-gray-700 mb-2">Category Breakdown</div>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {Object.entries(s.categories).map(([cat, data]) => (
                              <div key={cat} className="bg-white p-2 rounded border">
                                <div className="text-xs text-gray-500 capitalize">{cat}</div>
                                <div className="text-sm font-mono">
                                  {(data.accuracy * 100).toFixed(1)}%
                                  <span className="text-gray-400 text-xs ml-1">
                                    ({data.correct}/{data.total})
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Client Leaderboard */}
      <section>
        <h2 className="text-xl font-bold text-gray-900 mb-4">Client Leaderboard</h2>
        {leaderboard.length === 0 ? (
          <p className="text-gray-500">No client evaluations yet.</p>
        ) : (
          <div className="bg-white shadow rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Rank</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Agent Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Accuracy</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Badges</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {leaderboard.map((e) => (
                  <tr key={`${e.rank}-${e.agent_name}`} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{e.rank}</td>
                    <td className="px-4 py-3 text-sm text-gray-900">{e.agent_name || "-"}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{e.target_model}</td>
                    <td className="px-4 py-3 text-sm text-right font-mono">
                      {e.accuracy != null ? `${(e.accuracy * 100).toFixed(1)}%` : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <div className="flex gap-1 flex-wrap">
                        {e.badges.map((b) => (
                          <span
                            key={b}
                            className="inline-block bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded"
                          >
                            {b}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {e.completed_at ? new Date(e.completed_at).toLocaleDateString() : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
