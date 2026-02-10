"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "../../lib/api";
import RoleGuard from "../../components/RoleGuard";

interface User {
  id: number;
  username: string;
  role: string;
  groups: string;
  oauth_provider?: string;
  oauth_sub?: string;
}

interface AuthorityProfile {
  id: number;
  user_id: number;
  username: string;
  role: string;
  expertise_domains: string[];
  assigned_agent_ids: string[];
  availability: AvailabilityConfig;
  notification_config: NotificationConfig;
  created_at: string;
  updated_at: string;
}

interface AvailabilityConfig {
  timezone?: string;
  windows?: { days: number[]; start: string; end: string }[];
}

interface NotificationConfig {
  email?: { enabled: boolean; address: string };
  discord?: { enabled: boolean; webhook_url: string };
  in_app?: { enabled: boolean };
}

export default function UsersPage() {
  return (
    <RoleGuard allowed={["admin"]}>
      <UsersContent />
    </RoleGuard>
  );
}

function UsersContent() {
  const [users, setUsers] = useState<User[]>([]);
  const [profiles, setProfiles] = useState<AuthorityProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedUser, setExpandedUser] = useState<number | null>(null);

  // Invite form
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("wise_authority");
  const [inviting, setInviting] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [usersData, profilesData] = await Promise.all([
        apiFetch<User[]>("/auth/users"),
        apiFetch<AuthorityProfile[]>("/api/v1/admin/authorities").catch(
          () => [] as AuthorityProfile[]
        ),
      ]);
      setUsers(usersData);
      setProfiles(profilesData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const inviteUser = async () => {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    try {
      await apiFetch("/api/v1/admin/users/invite", {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      setInviteEmail("");
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to invite user");
    } finally {
      setInviting(false);
    }
  };

  const updateRole = async (username: string, newRole: string) => {
    try {
      await apiFetch(`/auth/users/${username}/role`, {
        method: "POST",
        body: JSON.stringify({ role: newRole }),
      });
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to update role");
    }
  };

  const deleteUser = async (username: string) => {
    if (!confirm(`Delete user ${username}?`)) return;
    try {
      await apiFetch(`/auth/users/${username}`, { method: "DELETE" });
      fetchData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete user");
    }
  };

  const getProfile = (userId: number) =>
    profiles.find((p) => p.user_id === userId);

  if (loading)
    return (
      <div className="text-center py-8 text-gray-500">Loading users...</div>
    );
  if (error)
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
        {error}
      </div>
    );

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">User Management</h2>

      {/* Invite Form */}
      <div className="bg-white shadow rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">
          Invite User
        </h3>
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label className="block text-xs text-gray-500 mb-1">Email</label>
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="user@example.com"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Role</label>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded text-sm"
            >
              <option value="wise_authority">Wise Authority</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <button
            onClick={inviteUser}
            disabled={inviting || !inviteEmail.trim()}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {inviting ? "Inviting..." : "Invite"}
          </button>
        </div>
      </div>

      {/* User Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Email
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Role
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Expertise
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Agents
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {users.map((user) => {
              const profile = getProfile(user.id);
              const isExpanded = expandedUser === user.id;
              return (
                <UserRow
                  key={user.id}
                  user={user}
                  profile={profile}
                  isExpanded={isExpanded}
                  onToggleExpand={() =>
                    setExpandedUser(isExpanded ? null : user.id)
                  }
                  onUpdateRole={updateRole}
                  onDelete={deleteUser}
                  onProfileUpdated={fetchData}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── User Row with expandable profile editor ── */

function UserRow({
  user,
  profile,
  isExpanded,
  onToggleExpand,
  onUpdateRole,
  onDelete,
  onProfileUpdated,
}: {
  user: User;
  profile?: AuthorityProfile;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onUpdateRole: (username: string, role: string) => void;
  onDelete: (username: string) => void;
  onProfileUpdated: () => void;
}) {
  return (
    <>
      <tr className="hover:bg-gray-50">
        <td className="px-4 py-3 text-sm">{user.username}</td>
        <td className="px-4 py-3 text-sm">
          <select
            value={user.role}
            onChange={(e) => onUpdateRole(user.username, e.target.value)}
            className="text-xs px-2 py-1 border border-gray-300 rounded"
          >
            <option value="admin">Admin</option>
            <option value="wise_authority">Wise Authority</option>
            <option value="anonymous">Anonymous</option>
          </select>
        </td>
        <td className="px-4 py-3 text-sm">
          {profile?.expertise_domains.length ? (
            <div className="flex flex-wrap gap-1">
              {profile.expertise_domains.map((d) => (
                <span
                  key={d}
                  className="text-xs px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded"
                >
                  {d}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-gray-400 text-xs">-</span>
          )}
        </td>
        <td className="px-4 py-3 text-sm">
          {profile?.assigned_agent_ids.length ? (
            <div className="flex flex-wrap gap-1">
              {profile.assigned_agent_ids.map((a) => (
                <span
                  key={a}
                  className="text-xs px-1.5 py-0.5 bg-green-100 text-green-700 rounded"
                >
                  {a}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-gray-400 text-xs">-</span>
          )}
        </td>
        <td className="px-4 py-3 text-sm flex gap-2">
          {(user.role === "wise_authority" || user.role === "admin") && (
            <button
              onClick={onToggleExpand}
              className="text-indigo-600 hover:text-indigo-800 text-xs"
            >
              {isExpanded ? "Close" : "Configure"}
            </button>
          )}
          <button
            onClick={() => onDelete(user.username)}
            className="text-red-600 hover:text-red-800 text-xs"
          >
            Remove
          </button>
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={5} className="bg-gray-50 px-4 py-4">
            <AuthorityProfileEditor
              userId={user.id}
              profile={profile}
              onSaved={onProfileUpdated}
            />
          </td>
        </tr>
      )}
    </>
  );
}

/* ── Authority Profile Editor ── */

function AuthorityProfileEditor({
  userId,
  profile,
  onSaved,
}: {
  userId: number;
  profile?: AuthorityProfile;
  onSaved: () => void;
}) {
  const [expertise, setExpertise] = useState(
    profile?.expertise_domains.join(", ") || ""
  );
  const [agents, setAgents] = useState(
    profile?.assigned_agent_ids.join(", ") || ""
  );
  const [timezone, setTimezone] = useState(
    profile?.availability.timezone || "UTC"
  );
  const [emailEnabled, setEmailEnabled] = useState(
    profile?.notification_config.email?.enabled || false
  );
  const [emailAddress, setEmailAddress] = useState(
    profile?.notification_config.email?.address || ""
  );
  const [discordEnabled, setDiscordEnabled] = useState(
    profile?.notification_config.discord?.enabled || false
  );
  const [discordWebhook, setDiscordWebhook] = useState(
    profile?.notification_config.discord?.webhook_url || ""
  );
  const [inAppEnabled, setInAppEnabled] = useState(
    profile?.notification_config.in_app?.enabled ?? true
  );
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        expertise_domains: expertise
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        assigned_agent_ids: agents
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        availability: { timezone, windows: profile?.availability.windows || [] },
        notification_config: {
          email: { enabled: emailEnabled, address: emailAddress },
          discord: { enabled: discordEnabled, webhook_url: discordWebhook },
          in_app: { enabled: inAppEnabled },
        },
      };
      await apiFetch(`/api/v1/admin/authorities/${userId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      onSaved();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 max-w-2xl">
      <h4 className="text-sm font-semibold text-gray-700">
        Authority Profile
      </h4>

      {/* Expertise */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">
          Expertise Domains (comma-separated)
        </label>
        <input
          type="text"
          value={expertise}
          onChange={(e) => setExpertise(e.target.value)}
          placeholder="ethics, finance, legal, safety"
          className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
        />
      </div>

      {/* Assigned Agents */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">
          Assigned Agent IDs (comma-separated)
        </label>
        <input
          type="text"
          value={agents}
          onChange={(e) => setAgents(e.target.value)}
          placeholder="agent_789, datum"
          className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
        />
      </div>

      {/* Timezone */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Timezone</label>
        <input
          type="text"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          placeholder="America/New_York"
          className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
        />
      </div>

      {/* Notifications */}
      <div className="space-y-3">
        <h5 className="text-xs font-semibold text-gray-600 uppercase">
          Notifications
        </h5>

        {/* Email */}
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={emailEnabled}
              onChange={(e) => setEmailEnabled(e.target.checked)}
            />
            Email
          </label>
          {emailEnabled && (
            <input
              type="email"
              value={emailAddress}
              onChange={(e) => setEmailAddress(e.target.value)}
              placeholder="user@example.com"
              className="flex-1 px-3 py-1 border border-gray-300 rounded text-sm"
            />
          )}
        </div>

        {/* Discord */}
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={discordEnabled}
              onChange={(e) => setDiscordEnabled(e.target.checked)}
            />
            Discord
          </label>
          {discordEnabled && (
            <input
              type="text"
              value={discordWebhook}
              onChange={(e) => setDiscordWebhook(e.target.value)}
              placeholder="https://discord.com/api/webhooks/..."
              className="flex-1 px-3 py-1 border border-gray-300 rounded text-sm"
            />
          )}
        </div>

        {/* In-App */}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={inAppEnabled}
            onChange={(e) => setInAppEnabled(e.target.checked)}
          />
          In-App (polls WBD task queue)
        </label>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50"
      >
        {saving ? "Saving..." : "Save Profile"}
      </button>
    </div>
  );
}
