"use client";
import React, { useEffect, useState } from "react";
import axios from "axios";

const API_BASE = "/api/v1";

interface User {
  id: number;
  username: string;
  role: string;
  groups: string;
  oauth_provider?: string;
  oauth_sub?: string;
}

type ErrorWithResponse = {
  response?: {
    data?: {
      detail?: string;
    };
  };
  message?: string;
};

export default function AdminTab() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [editRole, setEditRole] = useState("");
  const [editGroups, setEditGroups] = useState("");
  const [editOAuthProvider, setEditOAuthProvider] = useState("");
  const [editOAuthSub, setEditOAuthSub] = useState("");
  const [deleteUser, setDeleteUser] = useState<User | null>(null);

  // Replace with your JWT retrieval logic
  const token = typeof window !== "undefined" ? localStorage.getItem("authToken") : "";

  const fetchUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API_BASE}/auth/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setUsers(res.data);
    } catch (err: unknown) {
      setError(((err as ErrorWithResponse)?.response?.data?.detail || (err as ErrorWithResponse).message) ?? null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
    // eslint-disable-next-line
  }, []);

  const startEdit = (user: User) => {
    setEditUser(user);
    setEditRole(user.role);
    setEditGroups(user.groups || "");
    setEditOAuthProvider(user.oauth_provider || "");
    setEditOAuthSub(user.oauth_sub || "");
  };

  const saveEdit = async () => {
    if (!editUser) return;
    setLoading(true);
    setError(null);
    try {
      await axios.post(
        `${API_BASE}/auth/users/${encodeURIComponent(editUser.username)}/role`,
        { role: editRole },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      await axios.post(
        `${API_BASE}/auth/users/${encodeURIComponent(editUser.username)}/groups`,
        { groups: editGroups },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      await axios.post(
        `${API_BASE}/auth/users/${encodeURIComponent(editUser.username)}/oauth`,
        { oauth_provider: editOAuthProvider, oauth_sub: editOAuthSub },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setEditUser(null);
      fetchUsers();
    } catch (err: unknown) {
      const errorMsg = (err as ErrorWithResponse)?.response?.data?.detail ?? (err as ErrorWithResponse).message ?? null;
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteUser) return;
    setLoading(true);
    setError(null);
    try {
      await axios.delete(
        `${API_BASE}/auth/users/${encodeURIComponent(deleteUser.username)}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setDeleteUser(null);
      fetchUsers();
    } catch (err: unknown) {
      const errorMsg = (err as ErrorWithResponse)?.response?.data?.detail ?? (err as ErrorWithResponse).message ?? null;
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Admin: User Management</h2>
      {error && <div className="mb-4 text-red-600">{error}</div>}
      {loading && <div className="mb-4 text-gray-500">Loading...</div>}
      <table className="min-w-full bg-white border border-gray-200 rounded-lg overflow-hidden mb-8">
        <thead className="bg-gray-100">
          <tr>
            <th className="py-2 px-4 border-b">Username</th>
            <th className="py-2 px-4 border-b">Role</th>
            <th className="py-2 px-4 border-b">Groups</th>
            <th className="py-2 px-4 border-b">OAuth Provider</th>
            <th className="py-2 px-4 border-b">OAuth Sub</th>
            <th className="py-2 px-4 border-b">Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b hover:bg-gray-50">
              <td className="py-2 px-4">{u.username}</td>
              <td className="py-2 px-4">{u.role}</td>
              <td className="py-2 px-4">{u.groups}</td>
              <td className="py-2 px-4">{u.oauth_provider}</td>
              <td className="py-2 px-4">{u.oauth_sub}</td>
              <td className="py-2 px-4">
                <button
                  className="text-blue-600 hover:underline mr-2"
                  onClick={() => startEdit(u)}
                >
                  Edit
                </button>
                <button
                  className="text-red-600 hover:underline"
                  onClick={() => setDeleteUser(u)}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Edit Modal */}
      {editUser && (
        <div className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50">
          <div className="bg-white p-6 rounded-lg shadow-lg w-full max-w-md">
            <h3 className="text-xl font-bold mb-4">Edit User: {editUser.username}</h3>
            <div className="mb-2">
              <label className="block text-sm font-medium">Role</label>
              <input
                className="w-full border rounded px-2 py-1"
                value={editRole}
                onChange={e => setEditRole(e.target.value)}
              />
            </div>
            <div className="mb-2">
              <label className="block text-sm font-medium">Groups (comma-separated)</label>
              <input
                className="w-full border rounded px-2 py-1"
                value={editGroups}
                onChange={e => setEditGroups(e.target.value)}
              />
            </div>
            <div className="mb-2">
              <label className="block text-sm font-medium">OAuth Provider</label>
              <input
                className="w-full border rounded px-2 py-1"
                value={editOAuthProvider}
                onChange={e => setEditOAuthProvider(e.target.value)}
              />
            </div>
            <div className="mb-4">
              <label className="block text-sm font-medium">OAuth Sub</label>
              <input
                className="w-full border rounded px-2 py-1"
                value={editOAuthSub}
                onChange={e => setEditOAuthSub(e.target.value)}
              />
            </div>
            <div className="flex justify-end space-x-2">
              <button
                className="bg-gray-200 px-4 py-2 rounded hover:bg-gray-300"
                onClick={() => setEditUser(null)}
              >
                Cancel
              </button>
              <button
                className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
                onClick={saveEdit}
                disabled={loading}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Modal */}
      {deleteUser && (
        <div className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50">
          <div className="bg-white p-6 rounded-lg shadow-lg w-full max-w-md">
            <h3 className="text-xl font-bold mb-4">Delete User: {deleteUser.username}?</h3>
            <p className="mb-4">Are you sure you want to delete this user? This action cannot be undone.</p>
            <div className="flex justify-end space-x-2">
              <button
                className="bg-gray-200 px-4 py-2 rounded hover:bg-gray-300"
                onClick={() => setDeleteUser(null)}
              >
                Cancel
              </button>
              <button
                className="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-700"
                onClick={confirmDelete}
                disabled={loading}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
