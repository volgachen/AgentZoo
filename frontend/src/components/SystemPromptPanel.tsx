import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Session } from "../api/types";

export default function SystemPromptPanel({ session }: { session: Session }) {
  const [prompt, setPrompt] = useState("");
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
      {loading ? (
        <p className="px-2 text-xs text-gray-600">Loading system prompt…</p>
      ) : error ? (
        <div className="rounded border border-red-800 bg-red-950/50 px-2 py-1.5 text-[11px] leading-4 text-red-200">
          {error}
        </div>
      ) : (
        <>
          <pre className="flex-1 min-h-0 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-gray-700 bg-gray-950 p-2 font-mono text-[11px] leading-4 text-gray-200">
            {prompt || "(empty system prompt)"}
          </pre>
          <div className="shrink-0 px-2 pt-1.5 text-right font-mono text-[10px] text-gray-500">
            {prompt.length} chars
          </div>
        </>
      )}
    </section>
  );
}
