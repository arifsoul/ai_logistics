"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import ChartCanvas from "@/components/ChartCanvas";
import DataTable from "@/components/DataTable";
import { apiFetch, api, getToken } from "@/lib/api";
import { readFrames, type Turn } from "@/lib/frames";

const SESSION_KEY = "logistics_session_id";

const SAMPLES = [
  "Which carrier has the highest delay rate?",
  "Monthly order volume for 2025",
  "Top 10 SKUs by revenue",
  "Average delivery days per region",
  "Forecast stock for PAPER-0197 for 4 months",
];

export default function ChatPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const questionInput = useRef<HTMLInputElement>(null);
  // A ref, not state: nothing renders it, so it must not trigger a re-render.
  const sessionId = useRef("");

  // One session id per browser, reused so history survives a reload.
  function ensureSession() {
    if (!sessionId.current) {
      let id = window.localStorage.getItem(SESSION_KEY);
      if (!id) {
        id = crypto.randomUUID();
        window.localStorage.setItem(SESSION_KEY, id);
      }
      sessionId.current = id;
    }
    return sessionId.current;
  }

  const clearChat = useCallback(async () => {
    await apiFetch(`/api/history/${ensureSession()}`, {
      method: "DELETE",
    }).catch(() => undefined);
    const id = crypto.randomUUID();
    window.localStorage.setItem(SESSION_KEY, id);
    sessionId.current = id;
    setTurns([]);
  }, []);

  useEffect(() => {
    const id = ensureSession();
    if (!getToken()) return;
    api<{ history: Turn[] }>(`/api/history/${id}`)
      .then((data) => setTurns(data.history))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      const modifier = event.ctrlKey || event.metaKey;
      if (!modifier) return;

      if (event.key.toLowerCase() === "k") {
        event.preventDefault();
        questionInput.current?.focus();
      }
      if (event.key.toLowerCase() === "n") {
        event.preventDefault();
        void clearChat();
      }
    }

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [clearChat]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setQuestion("");
    setBusy(true);
    setTurns((current) => [
      ...current,
      { role: "user", content: message },
      { role: "assistant", content: "" },
    ]);

    // Mutate only the trailing assistant turn as frames arrive.
    const patch = (change: Partial<Turn>) =>
      setTurns((current) => {
        const next = [...current];
        next[next.length - 1] = { ...next[next.length - 1], ...change };
        return next;
      });

    try {
      const response = await apiFetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: ensureSession(),
        }),
      });
      if (!response.ok || !response.body) {
        const detail = await response.text();
        throw new Error(detail || `Request failed (${response.status})`);
      }
      let answer = "";
      for await (const frame of readFrames(response.body)) {
        if (frame.type === "token") {
          answer += frame.text;
          patch({ content: answer });
        } else if (frame.type === "sql") {
          patch({ sql: frame.sql });
        } else if (frame.type === "table") {
          patch({ table: frame });
        } else if (frame.type === "chart") {
          patch({ chart: frame.chart });
        } else if (frame.type === "error") {
          patch({ error: frame.message });
        }
      }
    } catch (caught) {
      patch({ error: caught instanceof Error ? caught.message : "Request failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 px-5 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Ask the database</h1>
          <p className="mt-1 text-sm text-slate-400">
            Every question becomes SQL over the logistics table. Answers come
            back as narrative, table and chart.
          </p>
        </div>
        <button
          type="button"
          onClick={clearChat}
          aria-keyshortcuts="Control+N Meta+N"
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold hover:border-rose-400 hover:text-rose-300"
        >
          New chat
        </button>
      </header>

      {!turns.length && (
        <div className="flex flex-wrap gap-2">
          {SAMPLES.map((sample) => (
            <button
              key={sample}
              type="button"
              onClick={() => send(sample)}
              className="rounded-full border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-cyan-400 hover:text-cyan-300"
            >
              {sample}
            </button>
          ))}
        </div>
      )}

      <section className="flex-1 space-y-4">
        {turns.map((turn, index) =>
          turn.role === "user" ? (
            <p
              key={index}
              className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950"
            >
              {turn.content}
            </p>
          ) : (
            <article
              key={index}
              className="max-w-full space-y-3 rounded-2xl rounded-bl-sm border border-slate-800 bg-slate-900 p-4"
            >
              {turn.error ? (
                <p role="alert" className="text-sm text-rose-400">
                  {turn.error}
                </p>
              ) : (
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                  {turn.content || (busy ? "Thinking…" : "")}
                </p>
              )}
              {turn.chart && <ChartCanvas spec={turn.chart} />}
              {turn.table && <DataTable table={turn.table} />}
              {turn.sql && (
                <details className="text-xs text-slate-400">
                  <summary className="cursor-pointer">Show SQL</summary>
                  <pre className="mt-2 overflow-auto rounded-lg bg-slate-950 p-3">
                    {turn.sql}
                  </pre>
                </details>
              )}
            </article>
          ),
        )}
        <div ref={bottom} />
      </section>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(question);
        }}
        className="sticky bottom-0 flex gap-2 border-t border-slate-800 bg-slate-950 py-3"
      >
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <input
          id="question"
          ref={questionInput}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. Which warehouse has the most delayed orders?"
          aria-keyshortcuts="Control+K Meta+K"
          className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-cyan-400"
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-60"
        >
          {busy ? "…" : "Ask"}
        </button>
      </form>
      <p className="text-center text-xs text-slate-500">
        Press <kbd className="rounded border border-slate-700 px-1.5 py-0.5">Ctrl/Cmd + K</kbd> to focus the question field or <kbd className="rounded border border-slate-700 px-1.5 py-0.5">Ctrl/Cmd + N</kbd> to start a new chat.
      </p>
    </main>
  );
}
