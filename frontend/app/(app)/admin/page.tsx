"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, getRole, me, type Role } from "@/lib/api";

type UserRow = { id: number; username: string; role: Role; password?: string | null };

const ROLES: Role[] = ["user", "admin", "superadmin"];
const MANAGEABLE_ROLES: Role[] = ["user", "admin"];

export default function AdminPage() {
  const router = useRouter();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<Record<number, string>>({});
  // Read from localStorage only after mount, otherwise the server render (no
  // role) and the first client render disagree and hydration fails.
  const [myId, setMyId] = useState(0);

  const load = () =>
    api<{ users: UserRow[] }>("/api/users")
      .then((data) => {
        setUsers(data.users);
      })
      .catch((caught) =>
        setError(caught instanceof Error ? caught.message : "Could not load"),
      );

  useEffect(() => {
    // The backend enforces this too; bouncing early avoids a bare 403 screen.
    const current = getRole();
    if (current !== "admin" && current !== "superadmin") {
      router.replace("/chat");
      return;
    }
    // Own id, so this account's own delete button can be hidden.
    me()
      .then((user) => setMyId(user.id))
      .catch(() => setMyId(0));
    load();
  }, [router]);

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      // This endpoint takes Form(...) fields, so send form-encoded.
      const created = await api<{ id: number }>("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username, password, role }),
      });
      setNotice(`Created ${username}`);
      setRevealed((current) => ({ ...current, [created.id]: password }));
      setUsername("");
      setPassword("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Create failed");
    }
  }

  async function changeRole(id: number, next: Role) {
    setError("");
    setNotice("");
    try {
      await api(`/api/users/${id}/role`, {
        method: "PUT",
        body: JSON.stringify({ role: next }),
      });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Update failed");
    }
  }

  async function resetPassword(row: UserRow) {
    setError("");
    setNotice("");
    if (!window.confirm(`Replace the password of ${row.username}?`)) return;
    try {
      const data = await api<{ password: string }>(
        `/api/users/${row.id}/reset-password`,
        { method: "POST" },
      );
      setRevealed((current) => ({ ...current, [row.id]: data.password }));
      setNotice(`New password for ${row.username}. Copy it now.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Reset failed");
    }
  }

  async function deleteUser(row: UserRow) {
    setError("");
    setNotice("");
    if (
      !window.confirm(
        `Delete ${row.username} and their chat history? This cannot be undone.`,
      )
    )
      return;
    try {
      await api(`/api/users/${row.id}`, { method: "DELETE" });
      setNotice(`Deleted ${row.username}`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed");
    }
  }

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 px-5 py-8">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">User management</h1>
        <p className="mt-2 text-slate-400">
          Create accounts, reset passwords and change roles. Passwords are stored
          hashed, so a reset shows the new one once. The superadmin account
          cannot be deleted.
        </p>
      </header>

      {error && (
        <p role="alert" className="text-rose-400">
          {error}
        </p>
      )}
      {notice && <p className="text-cyan-300">{notice}</p>}

      <form
        onSubmit={createUser}
        className="grid gap-3 rounded-xl border border-slate-800 bg-slate-900 p-5 sm:grid-cols-4"
      >
        <div>
          <label htmlFor="new-username" className="text-sm text-slate-400">
            Username
          </label>
          <input
            id="new-username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400"
          />
        </div>
        <div>
          <label htmlFor="new-password" className="text-sm text-slate-400">
            Password
          </label>
          <input
            id="new-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={4}
            autoComplete="new-password"
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400"
          />
        </div>
        <div>
          <label htmlFor="new-role" className="text-sm text-slate-400">
            Role
          </label>
          <select
            id="new-role"
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          >
            {MANAGEABLE_ROLES.map(
              (item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ),
            )}
          </select>
        </div>
        <button
          type="submit"
          className="self-end rounded-lg bg-cyan-500 px-4 py-2 text-sm font-bold text-slate-950"
        >
          Add user
        </button>
      </form>

      <div className="overflow-auto rounded-xl border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-slate-400">
            <tr>
              <th className="px-4 py-2 font-semibold">ID</th>
              <th className="px-4 py-2 font-semibold">Username</th>
              <th className="px-4 py-2 font-semibold">Password</th>
              <th className="px-4 py-2 font-semibold">Role</th>
              <th className="px-4 py-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((row) => (
              <tr key={row.id} className="border-t border-slate-800">
                <td className="px-4 py-2 text-slate-400">{row.id}</td>
                <td className="px-4 py-2 font-medium">{row.username}</td>
                <td className="px-4 py-2 font-mono text-cyan-300">
                  {revealed[row.id] ?? row.password ?? (
                    <span className="text-slate-500">••••••••</span>
                  )}
                </td>
                <td className="px-4 py-2">
                  <label htmlFor={`role-${row.id}`} className="sr-only">
                    Role for {row.username}
                  </label>
                  <select
                    id={`role-${row.id}`}
                    value={row.role}
                    disabled={row.username.toLowerCase() === "super@admin.com"}
                    onChange={(event) =>
                      changeRole(row.id, event.target.value as Role)
                    }
                    className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1"
                  >
                    {MANAGEABLE_ROLES.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-4 py-2">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      id={`reset-${row.id}`}
                      onClick={() => resetPassword(row)}
                      className="rounded-lg border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-300 hover:border-cyan-400 hover:text-cyan-300"
                    >
                      Reset password
                    </button>
                    {/* The superadmin is the way back into this page, and an
                        account cannot delete itself. The API refuses both. */}
                    {row.username.toLowerCase() !== "super@admin.com" &&
                      row.id !== myId && (
                      <button
                        type="button"
                        id={`delete-${row.id}`}
                        onClick={() => deleteUser(row)}
                        className="rounded-lg border border-rose-900 px-2 py-1 text-xs font-semibold text-rose-300 hover:border-rose-400"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
