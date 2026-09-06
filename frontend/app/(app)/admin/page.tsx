"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, getRole, me, type Role } from "@/lib/api";

type UserRow = { id: number; username: string; role: Role; password?: string | null };

const MANAGEABLE_ROLES: Role[] = ["user", "admin"];
const SUPERADMIN_USERNAME = "super@admin.com";

export default function AdminPage() {
  const router = useRouter();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<Record<number, string>>({});
  const [myId, setMyId] = useState(0);
  // AI config (admin-editable)
  const [aiBaseUrl, setAiBaseUrl] = useState("");
  const [embBaseUrl, setEmbBaseUrl] = useState("");
  const [aiApiKey, setAiApiKey] = useState("");
  const [embApiKey, setEmbApiKey] = useState("");
  const [aiModel, setAiModel] = useState("");
  const [embModel, setEmbModel] = useState("");
  const [embDim, setEmbDim] = useState("3072");
  const [aiModels, setAiModels] = useState<string[]>([]);
  const [embModels, setEmbModels] = useState<string[]>([]);
  const [cfgLoading, setCfgLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [aiModelsLoading, setAiModelsLoading] = useState(false);
  const [embModelsLoading, setEmbModelsLoading] = useState(false);
  const [aiModelsError, setAiModelsError] = useState("");
  const [embModelsError, setEmbModelsError] = useState("");
  const [embDims, setEmbDims] = useState<Record<string, number>>({});
  const [hasAiKey, setHasAiKey] = useState(false);
  const [hasEmbKey, setHasEmbKey] = useState(false);
  const [aiTest, setAiTest] = useState<{ ok: boolean; msg: string } | null>(null);
  const [embTest, setEmbTest] = useState<{ ok: boolean; msg: string } | null>(null);
  const [aiTesting, setAiTesting] = useState(false);
  const [embTesting, setEmbTesting] = useState(false);

  const load = () =>
    api<{ users: UserRow[] }>("/api/users")
      .then((data) => {
        setUsers(data.users);
      })
      .catch((caught) =>
        setError(caught instanceof Error ? caught.message : "Could not load"),
      );

  const loadCfg = () =>
    api<{ ai_base_url: string; embedding_base_url: string; ai_model: string; embedding_model: string; embedding_dim: number; has_ai_api_key: boolean; has_embedding_api_key: boolean; embedding_dims: Record<string, number> }>("/api/ai-config")
      .then((c) => {
        setAiBaseUrl(c.ai_base_url); setEmbBaseUrl(c.embedding_base_url);
        setAiModel(c.ai_model); setEmbModel(c.embedding_model); setEmbDim(String(c.embedding_dim));
        setHasAiKey(!!c.has_ai_api_key); setHasEmbKey(!!c.has_embedding_api_key);
        if (c.embedding_dims) setEmbDims(c.embedding_dims);
      })
      .catch(() => undefined);

  const fetchAiModels = async (base: string, kind: "chat" | "embedding") => {
    const isEmb = kind === "embedding";
    const key = isEmb ? embApiKey : aiApiKey;
    if (isEmb) { setEmbModelsLoading(true); setEmbModelsError(""); } else { setAiModelsLoading(true); setAiModelsError(""); }
    try {
      const params = new URLSearchParams({ kind });
      if (base.trim()) params.set("base_url", base.trim());
      if (key.trim()) params.set("api_key", key.trim());
      const d = await api<{ models: { id: string }[] }>(`/api/models?${params.toString()}`);
      const ids = d.models.map((m) => m.id);
      if (isEmb) setEmbModels(ids); else setAiModels(ids);
      if (!ids.length) {
        if (isEmb) setEmbModelsError("No models returned — check base URL / API key");
        else setAiModelsError("No models returned — check base URL / API key");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Fetch failed";
      if (isEmb) setEmbModelsError(msg); else setAiModelsError(msg);
    } finally {
      if (isEmb) setEmbModelsLoading(false); else setAiModelsLoading(false);
    }
  };

  const testAiModel = async () => {
    if (!aiModel.trim()) { setAiTest({ ok: false, msg: "Isi AI model dulu" }); return; }
    setAiTesting(true); setAiTest(null);
    try {
      const p = new URLSearchParams({ model: aiModel.trim(), kind: "chat" });
      if (aiBaseUrl.trim()) p.set("base_url", aiBaseUrl.trim());
      if (aiApiKey.trim()) p.set("api_key", aiApiKey.trim());
      const r = await api<{ valid: boolean; error?: string }>(`/api/models/validate?${p.toString()}`);
      setAiTest(r.valid ? { ok: true, msg: "Valid ✓" } : { ok: false, msg: r.error || "Model tidak ditemukan di endpoint" });
    } catch (e) { setAiTest({ ok: false, msg: e instanceof Error ? e.message : "Test failed" }); }
    finally { setAiTesting(false); }
  };
  const testEmbModel = async () => {
    if (!embModel.trim()) { setEmbTest({ ok: false, msg: "Isi embedding model dulu" }); return; }
    setEmbTesting(true); setEmbTest(null);
    try {
      const p = new URLSearchParams({ model: embModel.trim(), kind: "embedding" });
      if (embBaseUrl.trim()) p.set("base_url", embBaseUrl.trim());
      if (embApiKey.trim()) p.set("api_key", embApiKey.trim());
      const r = await api<{ valid: boolean; error?: string }>(`/api/models/validate?${p.toString()}`);
      setEmbTest(r.valid ? { ok: true, msg: "Valid ✓" } : { ok: false, msg: r.error || "Model tidak ditemukan di endpoint" });
    } catch (e) { setEmbTest({ ok: false, msg: e instanceof Error ? e.message : "Test failed" }); }
    finally { setEmbTesting(false); }
  };

  // Auto-fetch when base URL or API key changes (debounced)
  useEffect(() => {
    if (!aiBaseUrl) return;
    const t = setTimeout(() => { void fetchAiModels(aiBaseUrl, "chat"); }, 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiBaseUrl, aiApiKey]);
  useEffect(() => {
    if (!embBaseUrl) return;
    const t = setTimeout(() => { void fetchAiModels(embBaseUrl, "embedding"); }, 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embBaseUrl, embApiKey]);

  // Auto-adjust embedding dim when model changes
  useEffect(() => {
    const d = embDims[embModel] ?? embDims[embModel.toLowerCase()];
    if (d) setEmbDim(String(d));
  }, [embModel, embDims]);

  const saveCfg = async () => {
    setCfgLoading(true); setError(""); setNotice("");
    try {
      const body: Record<string, unknown> = { ai_base_url: aiBaseUrl, embedding_base_url: embBaseUrl, ai_model: aiModel, embedding_model: embModel, embedding_dim: parseInt(embDim, 10) };
      if (aiApiKey.trim()) body.ai_api_key = aiApiKey.trim();
      if (embApiKey.trim()) body.embedding_api_key = embApiKey.trim();
      await api("/api/ai-config", { method: "PUT", body: JSON.stringify(body) });
      setNotice("AI config saved — env vars remain fallback if DB keys cleared");
      setAiApiKey(""); setEmbApiKey("");
      await loadCfg();
    } catch (e) { setError(e instanceof Error ? e.message : "Save failed"); }
    finally { setCfgLoading(false); }
  };

  const syncCfg = async () => {
    setSyncing(true); setError(""); setNotice("");
    try {
      const body: Record<string, unknown> = { ai_base_url: aiBaseUrl, embedding_base_url: embBaseUrl, ai_model: aiModel, embedding_model: embModel, embedding_dim: parseInt(embDim, 10) };
      if (aiApiKey.trim()) body.ai_api_key = aiApiKey.trim();
      if (embApiKey.trim()) body.embedding_api_key = embApiKey.trim();
      const r = await api<{ documents: number; embedding_model: string }>("/api/ai-config/sync", { method: "POST", body: JSON.stringify(body) });
      setNotice(`Synced: ${r.documents} docs re-embedded with ${r.embedding_model}`);
      setAiApiKey(""); setEmbApiKey("");
      await loadCfg();
    } catch (e) { setError(e instanceof Error ? e.message : "Sync failed"); }
    finally { setSyncing(false); }
  };

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
    loadCfg();
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

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-4">
        <h2 className="text-lg font-semibold">AI & Embedding config</h2>
        <p className="text-xs text-slate-400">Base URL AI dan Embedding dipisah + API key masing-masing (kosongkan untuk pakai env var — production/local fallback). Dropdown auto-fetch dari base URL + key. Klik Test untuk validasi model, Sync untuk simpan + re-seed vector DB.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm text-slate-400">AI Base URL</label>
            <div className="mt-1 flex gap-1">
              <input value={aiBaseUrl} onChange={(e) => setAiBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" className="flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
              <button type="button" onClick={() => fetchAiModels(aiBaseUrl, "chat")} disabled={aiModelsLoading} className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold hover:border-cyan-400 disabled:opacity-50">{aiModelsLoading ? "…" : "Load"}</button>
            </div>
            <label className="text-sm text-slate-400">AI API Key {hasAiKey && !aiApiKey ? <span className="text-emerald-400">(env/DB ✓)</span> : null}</label>
            <div className="flex gap-1">
              <input type="password" value={aiApiKey} onChange={(e) => setAiApiKey(e.target.value)} placeholder={hasAiKey ? "•••••••• (kosongkan = pakai env/DB)" : "sk-..."} className="flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
              {hasAiKey && <button type="button" onClick={async () => { await api("/api/ai-config", { method: "PUT", body: JSON.stringify({ ai_api_key: "" }) }); setAiApiKey(""); await loadCfg(); setNotice("AI key cleared — fallback ke env var"); }} className="rounded-lg border border-slate-700 px-2 py-1 text-xs hover:border-rose-400">Clear</button>}
            </div>
            {aiModelsError && <p className="text-xs text-rose-400">{aiModelsError}</p>}
            <label className="text-sm text-slate-400">AI Model</label>
            {aiModels.length ? (
              <select value={aiModel} onChange={(e) => setAiModel(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
                {aiModels.map((m) => <option key={m} value={m}>{m}</option>)}
                {!aiModels.includes(aiModel) && aiModel && <option value={aiModel}>{aiModel} (current)</option>}
              </select>
            ) : (
              <input value={aiModel} onChange={(e) => setAiModel(e.target.value)} placeholder="gemini-flash-latest" className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
            )}
            <div className="flex items-center gap-2">
              <button type="button" onClick={testAiModel} disabled={aiTesting} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold hover:border-cyan-400 disabled:opacity-50">{aiTesting ? "Testing…" : "Test model"}</button>
              {aiTest && <span className={`text-xs ${aiTest.ok ? "text-emerald-400" : "text-rose-400"}`}>{aiTest.msg}</span>}
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-slate-400">Embedding Base URL</label>
            <div className="mt-1 flex gap-1">
              <input value={embBaseUrl} onChange={(e) => setEmbBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" className="flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
              <button type="button" onClick={() => fetchAiModels(embBaseUrl, "embedding")} disabled={embModelsLoading} className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold hover:border-cyan-400 disabled:opacity-50">{embModelsLoading ? "…" : "Load"}</button>
            </div>
            <label className="text-sm text-slate-400">Embedding API Key {hasEmbKey && !embApiKey ? <span className="text-emerald-400">(env/DB ✓)</span> : null}</label>
            <div className="flex gap-1">
              <input type="password" value={embApiKey} onChange={(e) => setEmbApiKey(e.target.value)} placeholder={hasEmbKey ? "•••••••• (kosongkan = pakai env/DB)" : "sk-..."} className="flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
              {hasEmbKey && <button type="button" onClick={async () => { await api("/api/ai-config", { method: "PUT", body: JSON.stringify({ embedding_api_key: "" }) }); setEmbApiKey(""); await loadCfg(); setNotice("Embedding key cleared — fallback ke env var"); }} className="rounded-lg border border-slate-700 px-2 py-1 text-xs hover:border-rose-400">Clear</button>}
            </div>
            {embModelsError && <p className="text-xs text-rose-400">{embModelsError}</p>}
            <label className="text-sm text-slate-400">Embedding Model (filter: embedding only)</label>
            {embModels.length ? (
              <select value={embModel} onChange={(e) => setEmbModel(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
                {embModels.map((m) => <option key={m} value={m}>{m}</option>)}
                {!embModels.includes(embModel) && embModel && <option value={embModel}>{embModel} (current)</option>}
              </select>
            ) : (
              <input value={embModel} onChange={(e) => setEmbModel(e.target.value)} placeholder="text-embedding-3-small" className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
            )}
            <div className="flex items-center gap-2">
              <button type="button" onClick={testEmbModel} disabled={embTesting} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold hover:border-cyan-400 disabled:opacity-50">{embTesting ? "Testing…" : "Test model"}</button>
              {embTest && <span className={`text-xs ${embTest.ok ? "text-emerald-400" : "text-rose-400"}`}>{embTest.msg}</span>}
            </div>
            <label className="text-sm text-slate-400">Embedding Dim {embDims[embModel] || embDims[embModel.toLowerCase()] ? <span className="text-slate-500">auto {embDims[embModel] ?? embDims[embModel.toLowerCase()]}</span> : null}</label>
            <input value={embDim} onChange={(e) => setEmbDim(e.target.value)} placeholder="3072" className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400" />
          </div>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={saveCfg} disabled={cfgLoading} className="rounded-lg border border-slate-700 px-4 py-2 text-sm font-semibold hover:border-cyan-400 disabled:opacity-50">Save</button>
          <button type="button" onClick={syncCfg} disabled={syncing} className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50">{syncing ? "Syncing…" : "Sync (save + re-seed vectors)"}</button>
        </div>
      </section>

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
                  {row.username.toLowerCase() === SUPERADMIN_USERNAME ? (
                    <span className="inline-flex rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-xs font-bold tracking-wide text-amber-300">
                      superadmin
                    </span>
                  ) : (
                    <>
                      <label htmlFor={`role-${row.id}`} className="sr-only">
                        Role for {row.username}
                      </label>
                      <select
                        id={`role-${row.id}`}
                        value={row.role}
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
                    </>
                  )}
                </td>
                <td className="px-4 py-2">
                  <div className="flex gap-2">
                    {row.username.toLowerCase() !== SUPERADMIN_USERNAME && (
                      <button
                        type="button"
                        id={`reset-${row.id}`}
                        onClick={() => resetPassword(row)}
                        className="rounded-lg border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-300 hover:border-cyan-400 hover:text-cyan-300"
                      >
                        Reset password
                      </button>
                    )}
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
