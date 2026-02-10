"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { apiFetch } from "../../lib/api";

/* -- WBD Types -- */
interface WBDTask {
  id: string;
  agent_task_id: string;
  payload: string;
  status: string;
  created_at: string;
  decision?: string;
  comment?: string;
  resolved_at?: string;
  assigned_to?: string;
  domain_hint?: string;
  notified_at?: string;
}

/* -- Agent Event Types -- */
interface AgentEvent {
  id: string;
  node_ts: string;
  agent_uid: string;
  event: Record<string, unknown>;
  archived?: boolean;
}

interface AuthorityUser {
  username: string;
  role: string;
}

export default function OversightPage() {
  const [tab, setTab] = useState<"wbd" | "events">("wbd");

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">Agent Oversight</h2>

      {/* Sub-tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        <button
          onClick={() => setTab("wbd")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "wbd"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          WBD Task Queue
        </button>
        <button
          onClick={() => setTab("events")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "events"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Agent Event Stream
        </button>
      </div>

      {tab === "wbd" ? <WBDQueue /> : <AgentEventStream />}
    </div>
  );
}

/* =============================================================================
   WBD Queue
   ============================================================================= */

function WBDQueue() {
  const { data: session } = useSession();
  const role = session?.user?.role || "anonymous";
  const isAdmin = role === "admin";

  const [tasks, setTasks] = useState<WBDTask[]>([]);
  const [authorities, setAuthorities] = useState<AuthorityUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolveId, setResolveId] = useState<string | null>(null);
  const [decision, setDecision] = useState("approve");
  const [comment, setComment] = useState("");

  const fetchTasks = useCallback(async () => {
    try {
      const data = await apiFetch<{ tasks: WBDTask[] }>("/api/v1/wbd/tasks");
      setTasks(data.tasks || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load WBD tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch authority users for reassignment dropdown (admin only)
  useEffect(() => {
    if (!isAdmin) return;
    apiFetch<AuthorityUser[]>("/auth/users")
      .then((users) =>
        setAuthorities(
          users.filter(
            (u) => u.role === "wise_authority" || u.role === "admin"
          )
        )
      )
      .catch(() => {});
  }, [isAdmin]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  const resolveTask = async () => {
    if (!resolveId) return;
    try {
      await apiFetch(`/api/v1/wbd/tasks/${resolveId}/resolve`, {
        method: "POST",
        body: JSON.stringify({ decision, comment }),
      });
      setResolveId(null);
      setComment("");
      fetchTasks();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to resolve task");
    }
  };

  const reassignTask = async (taskId: string, assignee: string) => {
    try {
      await apiFetch(`/api/v1/wbd/tasks/${taskId}/assign`, {
        method: "PATCH",
        body: JSON.stringify({ assigned_to: assignee }),
      });
      fetchTasks();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to reassign task");
    }
  };

  const slaRemaining = (createdAt: string) => {
    const created = new Date(createdAt).getTime();
    const slaMs = 24 * 60 * 60 * 1000;
    const remaining = slaMs - (Date.now() - created);
    if (remaining <= 0)
      return <span className="text-red-600 font-medium">Expired</span>;
    const hours = Math.floor(remaining / 3600000);
    if (hours < 6) return <span className="text-red-600">{hours}h</span>;
    if (hours < 12) return <span className="text-yellow-600">{hours}h</span>;
    return <span className="text-green-600">{hours}h</span>;
  };

  const pendingTasks = tasks.filter(
    (t) => t.status === "open" || t.status === "pending" || t.status === "sla_breached"
  );
  const resolvedTasks = tasks.filter(
    (t) => t.status !== "open" && t.status !== "pending" && t.status !== "sla_breached"
  );

  if (loading)
    return (
      <div className="text-center py-8 text-gray-500">
        Loading WBD tasks...
      </div>
    );
  if (error)
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
        {error}
      </div>
    );

  return (
    <div className="space-y-6">
      {/* Resolve Form */}
      {resolveId && (
        <div className="bg-white shadow rounded-lg p-4 border-l-4 border-indigo-600">
          <h4 className="font-semibold text-gray-900 mb-3">
            Resolve Task: {resolveId}
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Decision
              </label>
              <select
                value={decision}
                onChange={(e) => setDecision(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
              >
                <option value="approve">Approve</option>
                <option value="reject">Reject</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Comment
              </label>
              <input
                type="text"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                placeholder="Optional comment..."
              />
            </div>
          </div>
          <div className="flex gap-2 mt-3">
            <button
              onClick={resolveTask}
              className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700"
            >
              Submit
            </button>
            <button
              onClick={() => setResolveId(null)}
              className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Pending Tasks */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-gray-900">
            Pending Tasks ({pendingTasks.length})
          </h3>
          <button
            onClick={fetchTasks}
            className="text-sm text-indigo-600 hover:text-indigo-800"
          >
            Refresh
          </button>
        </div>
        {pendingTasks.length === 0 ? (
          <p className="text-gray-500">No pending WBD tasks.</p>
        ) : (
          <div className="bg-white shadow rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Task ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Agent Task ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Assigned To
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Domain
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Created
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    SLA
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {pendingTasks.map((t) => (
                  <tr key={t.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-mono">{t.id}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {t.agent_task_id}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {isAdmin ? (
                        <select
                          value={t.assigned_to || ""}
                          onChange={(e) =>
                            e.target.value &&
                            reassignTask(t.id, e.target.value)
                          }
                          className="text-xs px-2 py-1 border border-gray-300 rounded"
                        >
                          <option value="">Unassigned</option>
                          {authorities.map((a) => (
                            <option key={a.username} value={a.username}>
                              {a.username}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className="text-xs">
                          {t.assigned_to || (
                            <span className="text-gray-400">Unassigned</span>
                          )}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {t.domain_hint || "-"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span
                        className={`text-xs px-2 py-0.5 rounded font-medium ${
                          t.status === "sla_breached"
                            ? "bg-red-100 text-red-700"
                            : "bg-yellow-100 text-yellow-700"
                        }`}
                      >
                        {t.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {new Date(t.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {slaRemaining(t.created_at)}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <button
                        onClick={() => setResolveId(t.id)}
                        className="text-indigo-600 hover:text-indigo-800 font-medium"
                      >
                        Resolve
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Resolved Tasks (collapsed) */}
      {resolvedTasks.length > 0 && (
        <details className="bg-white shadow rounded-lg">
          <summary className="px-4 py-3 cursor-pointer text-sm font-medium text-gray-700 hover:bg-gray-50">
            Resolved Tasks ({resolvedTasks.length})
          </summary>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    Task ID
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    Assigned To
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    Decision
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    Comment
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    Resolved At
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {resolvedTasks.map((t) => (
                  <tr key={t.id}>
                    <td className="px-4 py-2 text-sm font-mono">{t.id}</td>
                    <td className="px-4 py-2 text-sm text-gray-500">
                      {t.assigned_to || "-"}
                    </td>
                    <td className="px-4 py-2 text-sm">
                      <span
                        className={`text-xs px-2 py-0.5 rounded font-medium ${
                          t.decision === "approve"
                            ? "bg-green-100 text-green-700"
                            : "bg-red-100 text-red-700"
                        }`}
                      >
                        {t.decision}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-500">
                      {t.comment || "-"}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-500">
                      {t.resolved_at
                        ? new Date(t.resolved_at).toLocaleString()
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

/* =============================================================================
   Agent Event Stream
   ============================================================================= */

function AgentEventStream() {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [uidFilter, setUidFilter] = useState("");

  const fetchEvents = useCallback(async () => {
    try {
      const data = await apiFetch<AgentEvent[]>("/api/v1/agent/events");
      setEvents(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load events");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEvents();
    const interval = setInterval(fetchEvents, 10000);
    return () => clearInterval(interval);
  }, [fetchEvents]);

  const archiveEvent = async (id: string, archived: boolean) => {
    try {
      await apiFetch(
        `/api/v1/agent/events/${id}/archive?archived=${archived}`,
        { method: "PATCH" }
      );
      setEvents((prev) =>
        prev.map((e) => (e.id === id ? { ...e, archived } : e))
      );
    } catch {
      alert("Failed to update archive status");
    }
  };

  const deleteEvent = async (id: string) => {
    if (!confirm("Delete this event?")) return;
    try {
      await apiFetch(`/api/v1/agent/events/${id}`, { method: "DELETE" });
      setEvents((prev) => prev.filter((e) => e.id !== id));
    } catch {
      alert("Failed to delete event");
    }
  };

  const filtered = events
    .filter((e) => showArchived || !e.archived)
    .filter(
      (e) =>
        !uidFilter ||
        e.agent_uid.toLowerCase().includes(uidFilter.toLowerCase())
    );

  if (loading)
    return (
      <div className="text-center py-8 text-gray-500">Loading events...</div>
    );
  if (error)
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
        {error}
      </div>
    );

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-4">
        <input
          type="text"
          value={uidFilter}
          onChange={(e) => setUidFilter(e.target.value)}
          placeholder="Filter by agent UID..."
          className="px-3 py-2 border border-gray-300 rounded text-sm w-64"
        />
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          Show archived
        </label>
        <button
          onClick={fetchEvents}
          className="text-sm text-indigo-600 hover:text-indigo-800 ml-auto"
        >
          Refresh
        </button>
      </div>

      {filtered.length === 0 ? (
        <p className="text-gray-500">No agent events found.</p>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Agent UID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Event Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Timestamp
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {filtered.map((ev) => (
                <tr
                  key={ev.id}
                  className={`hover:bg-gray-50 ${ev.archived ? "opacity-50" : ""}`}
                >
                  <td className="px-4 py-3 text-sm font-mono text-gray-700">
                    {ev.id}
                  </td>
                  <td className="px-4 py-3 text-sm">{ev.agent_uid}</td>
                  <td className="px-4 py-3 text-sm">
                    <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700">
                      {(ev.event?.type as string) || "unknown"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {new Date(ev.node_ts).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-sm flex gap-2">
                    <button
                      onClick={() => archiveEvent(ev.id, !ev.archived)}
                      className="text-gray-600 hover:text-gray-800 text-xs"
                    >
                      {ev.archived ? "Unarchive" : "Archive"}
                    </button>
                    <button
                      onClick={() => deleteEvent(ev.id)}
                      className="text-red-600 hover:text-red-800 text-xs"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
