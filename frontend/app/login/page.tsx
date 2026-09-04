"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { login, register } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "register") {
        await register(username, password);
      }
      await login(username, password);
      router.replace("/chat");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center px-5 py-10">
      <div className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-7">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-cyan-400">
          Logistics AI
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">
          {mode === "login" ? "Sign in" : "Create an account"}
        </h1>

        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="username" className="text-sm text-slate-400">
              Username
            </label>
            <input
              id="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              autoComplete="username"
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400"
            />
          </div>
          <div>
            <label htmlFor="password" className="text-sm text-slate-400">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={4}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-rose-400">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-cyan-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-60"
          >
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Register"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError("");
          }}
          className="mt-5 text-sm text-slate-400 underline hover:text-cyan-300"
        >
          {mode === "login"
            ? "No account? Register"
            : "Already registered? Sign in"}
        </button>

        <p className="mt-6 text-xs text-slate-500">
          Questions are answered from the logistics Postgres database.{" "}
          <Link href="/chat" className="underline">
            Go to chat
          </Link>{" "}
          after signing in.
        </p>
      </div>
    </main>
  );
}
