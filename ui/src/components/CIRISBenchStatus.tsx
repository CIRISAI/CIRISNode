"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";

interface SSEEvent {
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

interface SystemStatus {
  health: string;
  concurrency: {
    limit?: number;
    active?: number;
    waiting?: number;
    available?: number;
  };
  subscribers: number;
  uptime_seconds: number;
}

interface CIRISBenchStatusProps {
  apiBaseUrl?: string;
}

const MAX_EVENTS = 200;

export default function CIRISBenchStatus({ apiBaseUrl }: CIRISBenchStatusProps) {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [filter, setFilter] = useState<string>("all");

  const eventSourceRef = useRef<EventSource | null>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);

  const API_BASE = apiBaseUrl || process.env.NEXT_PUBLIC_ETHICSENGINE_API || "http://localhost:8080";

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setConnecting(true);
    setError(null);

    const eventSource = new EventSource(`${API_BASE}/sse/stream`);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      setConnected(true);
      setConnecting(false);
      setError(null);
    };

    eventSource.onerror = () => {
      setConnected(false);
      setConnecting(false);
      setError("Connection lost. Click Connect to reconnect.");
      eventSource.close();
    };

    // Listen for all event types
    const eventTypes = [
      "connected",
      "status",
      "log",
      "benchmark_start",
      "benchmark_progress",
      "benchmark_complete",
      "test",
      "error",
    ];

    eventTypes.forEach((eventType) => {
      eventSource.addEventListener(eventType, (e: MessageEvent) => {
        try {
          const payload = JSON.parse(e.data);
          const event: SSEEvent = {
            type: payload.type || eventType,
            timestamp: payload.timestamp || new Date().toISOString(),
            data: payload.data || {},
          };

          // Update system status if it's a status event
          if (eventType === "status" && payload.data) {
            setSystemStatus(payload.data as SystemStatus);
          }

          setEvents((prev) => {
            const newEvents = [...prev, event];
            // Keep only the last MAX_EVENTS
            return newEvents.slice(-MAX_EVENTS);
          });
        } catch (err) {
          console.error("Failed to parse SSE event:", err);
        }
      });
    });

    return () => {
      eventSource.close();
    };
  }, [API_BASE]);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setConnected(false);
    setConnecting(false);
  }, []);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const clearEvents = () => {
    setEvents([]);
  };

  const filteredEvents = events.filter((event) => {
    if (filter === "all") return true;
    if (filter === "benchmark") return event.type.startsWith("benchmark_");
    if (filter === "log") return event.type === "log";
    if (filter === "status") return event.type === "status";
    return event.type === filter;
  });

  const getEventColor = (type: string) => {
    switch (type) {
      case "benchmark_start":
        return "text-blue-400";
      case "benchmark_progress":
        return "text-cyan-400";
      case "benchmark_complete":
        return "text-green-400";
      case "error":
        return "text-red-400";
      case "log":
        return "text-gray-400";
      case "status":
        return "text-yellow-400";
      case "connected":
        return "text-emerald-400";
      default:
        return "text-gray-300";
    }
  };

  const getLogLevelColor = (level?: string) => {
    switch (level) {
      case "ERROR":
        return "text-red-400";
      case "WARNING":
        return "text-yellow-400";
      case "INFO":
        return "text-blue-400";
      case "DEBUG":
        return "text-gray-500";
      default:
        return "text-gray-400";
    }
  };

  const formatTimestamp = (ts: string) => {
    try {
      const date = new Date(ts);
      return date.toLocaleTimeString("en-US", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return ts;
    }
  };

  const formatUptime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }
    if (minutes > 0) {
      return `${minutes}m ${secs}s`;
    }
    return `${secs}s`;
  };

  const renderEventContent = (event: SSEEvent) => {
    const { type, data } = event;

    switch (type) {
      case "log":
        return (
          <span className={getLogLevelColor(data.level as string)}>
            [{data.level as string}] {data.logger as string}: {data.message as string}
          </span>
        );

      case "benchmark_start":
        return (
          <span>
            <span className="text-blue-400 font-semibold">BENCHMARK START</span>
            {" "}{data.batch_id as string} - {data.total_scenarios as number} scenarios
            {data.agent_name ? ` (${data.agent_name as string})` : ""}
          </span>
        );

      case "benchmark_progress":
        return (
          <span>
            <span className="text-cyan-400">PROGRESS</span>
            {" "}{data.batch_id as string}: {data.completed as number}/{data.total as number}
            {" "}({((data.accuracy as number) * 100).toFixed(1)}% accuracy)
          </span>
        );

      case "benchmark_complete":
        return (
          <span>
            <span className="text-green-400 font-semibold">BENCHMARK COMPLETE</span>
            {" "}{data.batch_id as string}: {data.correct as number}/{data.total as number}
            {" "}({((data.accuracy as number) * 100).toFixed(1)}%)
            {" "}- {(data.processing_time_ms as number).toFixed(0)}ms
          </span>
        );

      case "status":
        return (
          <span className="text-gray-500">
            System status: {data.health as string}, {data.subscribers as number} subscribers
          </span>
        );

      case "connected":
        return (
          <span className="text-emerald-400 font-semibold">
            SSE stream connected ({data.subscribers as number} subscribers)
          </span>
        );

      case "error":
        return (
          <span className="text-red-400">
            ERROR: {data.message as string || JSON.stringify(data)}
          </span>
        );

      default:
        return <span>{JSON.stringify(data)}</span>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-gray-800 to-gray-900 rounded-lg p-6 text-white">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <span>📡</span> CIRISBench Live Status
        </h2>
        <p className="mt-2 text-gray-300">
          Real-time Server-Sent Events stream from the CIRISBench API
        </p>
        <div className="mt-3 flex items-center gap-3">
          <span
            className={`px-2 py-1 rounded text-xs font-medium ${
              connected
                ? "bg-green-500 bg-opacity-30 text-green-300"
                : connecting
                ? "bg-yellow-500 bg-opacity-30 text-yellow-300"
                : "bg-red-500 bg-opacity-30 text-red-300"
            }`}
          >
            {connected ? "● Connected" : connecting ? "◌ Connecting..." : "○ Disconnected"}
          </span>
          <span className="px-2 py-1 bg-gray-700 rounded text-xs font-mono">
            {API_BASE}/sse/stream
          </span>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-white shadow rounded-lg p-4">
        <div className="flex flex-wrap items-center gap-4">
          {/* Connection controls */}
          <div className="flex gap-2">
            {!connected ? (
              <button
                onClick={connect}
                disabled={connecting}
                className="px-4 py-2 bg-green-600 text-white font-medium rounded-md hover:bg-green-700 disabled:bg-gray-400 transition-colors"
              >
                {connecting ? "Connecting..." : "Connect"}
              </button>
            ) : (
              <button
                onClick={disconnect}
                className="px-4 py-2 bg-red-600 text-white font-medium rounded-md hover:bg-red-700 transition-colors"
              >
                Disconnect
              </button>
            )}
            <button
              onClick={clearEvents}
              className="px-4 py-2 bg-gray-600 text-white font-medium rounded-md hover:bg-gray-700 transition-colors"
            >
              Clear
            </button>
          </div>

          {/* Filter */}
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600">Filter:</label>
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="rounded-md border-gray-300 shadow-sm text-sm"
            >
              <option value="all">All Events</option>
              <option value="benchmark">Benchmark</option>
              <option value="log">Logs</option>
              <option value="status">Status</option>
            </select>
          </div>

          {/* Auto-scroll toggle */}
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded border-gray-300"
            />
            Auto-scroll
          </label>

          {/* Event count */}
          <span className="text-sm text-gray-500">
            {filteredEvents.length} / {events.length} events
          </span>
        </div>

        {error && (
          <div className="mt-3 p-2 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
            {error}
          </div>
        )}
      </div>

      {/* System Status Panel */}
      {systemStatus && (
        <div className="bg-white shadow rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3">System Status</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <p
                className={`text-lg font-bold ${
                  systemStatus.health === "healthy" ? "text-green-600" : "text-red-600"
                }`}
              >
                {systemStatus.health}
              </p>
              <p className="text-xs text-gray-500">Health</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <p className="text-lg font-bold text-blue-600">
                {systemStatus.concurrency?.active || 0}
              </p>
              <p className="text-xs text-gray-500">Active Tasks</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <p className="text-lg font-bold text-gray-600">
                {systemStatus.concurrency?.limit || 0}
              </p>
              <p className="text-xs text-gray-500">Concurrency Limit</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <p className="text-lg font-bold text-purple-600">{systemStatus.subscribers}</p>
              <p className="text-xs text-gray-500">SSE Subscribers</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <p className="text-lg font-bold text-gray-600">
                {formatUptime(systemStatus.uptime_seconds)}
              </p>
              <p className="text-xs text-gray-500">Uptime</p>
            </div>
          </div>
        </div>
      )}

      {/* Event Log */}
      <div className="bg-gray-900 rounded-lg shadow-lg overflow-hidden">
        <div className="px-4 py-2 bg-gray-800 border-b border-gray-700 flex justify-between items-center">
          <h3 className="text-sm font-medium text-gray-300">Event Stream</h3>
          <span className="text-xs text-gray-500">
            Showing {filter === "all" ? "all" : filter} events
          </span>
        </div>
        <div
          ref={logContainerRef}
          className="h-96 overflow-y-auto font-mono text-sm p-4 space-y-1"
        >
          {filteredEvents.length === 0 ? (
            <div className="text-gray-500 text-center py-8">
              {connected
                ? "Waiting for events..."
                : "Connect to start receiving events"}
            </div>
          ) : (
            filteredEvents.map((event, idx) => (
              <div key={idx} className="flex gap-2 hover:bg-gray-800 px-1 rounded">
                <span className="text-gray-500 flex-shrink-0">
                  {formatTimestamp(event.timestamp)}
                </span>
                <span className={`${getEventColor(event.type)} flex-shrink-0`}>
                  [{event.type.toUpperCase().substring(0, 8).padEnd(8)}]
                </span>
                <span className="text-gray-300 break-all">
                  {renderEventContent(event)}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* API Info */}
      <div className="text-xs text-gray-500 text-center">
        SSE Endpoint: <code className="bg-gray-100 px-2 py-1 rounded">{API_BASE}/sse/stream</code>
        {" | "}
        History: <code className="bg-gray-100 px-2 py-1 rounded">GET /sse/history</code>
        {" | "}
        Test: <code className="bg-gray-100 px-2 py-1 rounded">POST /sse/test</code>
      </div>
    </div>
  );
}
