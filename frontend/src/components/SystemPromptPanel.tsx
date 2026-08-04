import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Session } from "../api/types";

export default function SystemPromptPanel({ session }: { session: Session }) {
  const [prompt, setPrompt] = useState("");
  const [source, setSource] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.sessions
      .systemPrompt(session.id)
      .then((result) => {
        if (!cancelled) {
          setPrompt(result.system_prompt);
          setSource(result.source ?? null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session.id]);

  return (
    <section className="flex-1 flex flex-col min-h-0">
      <div className="shrink-0 flex items-center justify-between px-2 pb-1.5">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          System Prompt
        </h2>
        <span className="text-[10px] text-gray-500 font-mono">
          {prompt.length} chars
        </span>
      </div>
      <div className="px-2 pb-2 text-[11px] leading-4 text-gray-500">
        Effective prompt for this session. Source: <span className="font-mono text-gray-400">{source ?? "—"}</span>.
      </div>
      {loading ? (
        <p className="px-2 text-xs text-gray-600">Loading system prompt…</p>
      ) : error ? (
        <div className="rounded border border-red-800 bg-red-950/50 px-2 py-1.5 text-[11px] leading-4 text-red-200">
          {error}
        </div>
      ) : (
        <pre className="flex-1 min-h-0 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-gray-700 bg-gray-950 p-2 font-mono text-[11px] leading-4 text-gray-200">
          {prompt || "(empty system prompt)"}
        </pre>
      )}
    </section>
  );
}
