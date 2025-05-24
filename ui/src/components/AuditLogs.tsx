"use client";
import React, { useEffect, useState } from "react";
import axios from "axios";

interface AuditLog {
  id: string;
  timestamp: string;
  actor: string;
  event_type: string;
  payload_sha256: string;
  details: unknown;
  archived?: boolean;
}

interface Result {
  scenario_id: string;
  prompt: string;
  model_used: string;
  response: string;
  expected_answer: string;
  passed: boolean;
}

const AuditLogs: React.FC = () => {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  const fetchLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get("/api/v1/audit/logs");
      setLogs(res.data.logs || []);
    } catch {
      setError("Failed to fetch audit logs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  // If not loading and logs is empty, show a test log
  const displayLogs = !loading && logs.length === 0
    ? [{
        id: "test-log-1",
        timestamp: new Date().toISOString(),
        actor: "system",
        event_type: "test_event",
        payload_sha256: "testhash",
        details: { message: "This is a test audit log." },
        archived: false,
      }]
    : logs;

  return (
    <div style={{ margin: "20px auto", maxWidth: 900 }}>
      <h2>Audit Logs</h2>
      <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
        <button
          onClick={fetchLogs}
          style={{
            padding: "6px 16px",
            background: "#4F46E5",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
            fontWeight: "bold"
          }}
        >
          Refresh Logs
        </button>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="checkbox"
            checked={showArchived}
            onChange={e => setShowArchived(e.target.checked)}
          />
          Show Archived
        </label>
      </div>
      {loading && <p>Loading audit logs...</p>}
      {error && <div style={{ color: "red" }}>{error}</div>}
      {!loading && logs.length === 0 && <p>No audit logs found.</p>}
      {!loading && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>ID</th>
              <th>Timestamp</th>
              <th>Actor</th>
              <th>Event Type</th>
              <th>Payload SHA256</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {displayLogs
              .filter(log => showArchived || !log.archived)
              .map((log, idx) => (
              <tr key={log.id ?? `${log.timestamp}-${log.event_type}-${idx}`}>
                <td>{log.id}</td>
                <td>{log.timestamp}</td>
                <td>{log.actor}</td>
                <td>{log.event_type}</td>
                <td style={{ fontFamily: "monospace", fontSize: "0.9em" }}>{log.payload_sha256}</td>
                <td>
                  <div style={{ maxWidth: 400, maxHeight: 200, overflow: "auto", background: "#f9f9f9", borderRadius: 4, padding: 6 }}>
                    {(() => {
                      try {
                        const parsed = typeof log.details === "string" ? JSON.parse(log.details) : log.details;
                        if (parsed && typeof parsed === "object" && Array.isArray(parsed.results)) {
                          return (
                            <div>
                              <strong>Results:</strong>
                              {parsed.results.map((r: Result, idx: number) => (
                                <div key={idx} style={{ border: "1px solid #ddd", borderRadius: 4, margin: "6px 0", padding: 6, background: "#fff" }}>
                                  <div><strong>Scenario ID:</strong> {r.scenario_id}</div>
                                  <div><strong>Prompt:</strong> <span style={{ fontSize: "0.85em" }}>{r.prompt}</span></div>
                                  <div><strong>Model Used:</strong> {r.model_used}</div>
                                  <div><strong>Output:</strong> <pre style={{ fontSize: "0.85em", background: "#f4f4f4", padding: 4, borderRadius: 3 }}>{r.response}</pre></div>
                                  <div><strong>Expected Answer:</strong> {r.expected_answer}</div>
                                  <div>
                                    <strong>Status:</strong>{" "}
                                    <span style={{ color: r.passed ? "#2b8a3e" : "#c92a2a", fontWeight: "bold" }}>
                                      {r.passed ? "✓ Passed" : "✗ Failed"}
                                    </span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          );
                        }
                        return <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.9em" }}>{JSON.stringify(parsed, null, 2)}</pre>;
                      } catch {
                        return <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.9em" }}>{String(log.details)}</pre>;
                      }
                    })()}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <button
                      onClick={async () => {
                        if (window.confirm("Delete this audit log?")) {
                          try {
                            await axios.delete(`/api/v1/audit/logs/${log.id}`);
                            setLogs((prev) => prev.filter((l) => l.id !== log.id));
                          } catch {
                            alert("Failed to delete audit log.");
                          }
                        }
                      }}
                      style={{
                        background: "#c92a2a",
                        color: "#fff",
                        padding: "4px 10px",
                        border: "none",
                        borderRadius: 4,
                        fontWeight: "bold",
                        cursor: "pointer"
                      }}
                    >
                      Delete
                    </button>
                    <button
                      onClick={async () => {
                        try {
                          await axios.patch(`/api/v1/audit/logs/${log.id}/archive?archived=${log.archived ? "false" : "true"}`);
                          setLogs((prev) =>
                            prev.map((l) =>
                              l.id === log.id ? { ...l, archived: !log.archived } : l
                            )
                          );
                        } catch {
                          alert("Failed to update archive status.");
                        }
                      }}
                      style={{
                        background: log.archived ? "#aaa" : "#4F46E5",
                        color: "#fff",
                        padding: "4px 10px",
                        border: "none",
                        borderRadius: 4,
                        fontWeight: "bold",
                        cursor: "pointer"
                      }}
                    >
                      {log.archived ? "Unarchive" : "Archive"}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

export default AuditLogs;
