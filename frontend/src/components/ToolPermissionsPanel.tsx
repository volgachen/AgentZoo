import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Session } from "../api/types";

const DEFAULT_TOOL_PERMISSIONS = {
  default: "ask",
  rules: [
    {
      id: "allow-read-workspace",
      effect: "allow",
      tool: "read",
      paths: ["./**"],
    },
    {
      id: "deny-sensitive-files",
      effect: "deny",
      tool: "*",
      paths: ["./.env", "./.env.*", "./secrets/**", "./.git/**"],
    },
  ],
};

function pretty(value: unknown): string {
  return JSON.stringify(value ?? DEFAULT_TOOL_PERMISSIONS, null, 2);
}

function permissionsFromConfig(config: Record<string, unknown> | null): unknown {
  return config?.tool_permissions ?? DEFAULT_TOOL_PERMISSIONS;
}

export default function ToolPermissionsPanel({ session }: { session: Session }) {
  const [sessionConfig, setSessionConfig] = useState<Record<string, unknown> | null>(null);
  const [draft, setDraft] = useState(pretty(DEFAULT_TOOL_PERMISSIONS));
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSaved(false);
    api.sessions
      .config(session.id)
      .then((config) => {
        if (cancelled) return;
        setSessionConfig(config);
        setDraft(pretty(permissionsFromConfig(config)));
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

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const parsed = JSON.parse(draft) as unknown;
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("tool_permissions must be a JSON object");
      }
      const nextConfig = {
        ...(sessionConfig ?? { version: 1 }),
        tool_permissions: parsed,
      };
      const updated = await api.sessions.updateConfig(session.id, nextConfig);
      setSessionConfig(updated);
      setDraft(pretty(permissionsFromConfig(updated)));
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setDraft(pretty(permissionsFromConfig(sessionConfig)));
    setError(null);
    setSaved(false);
  };

  return (
    <section className="flex-1 flex flex-col min-h-0">
      <div className="shrink-0 flex items-center justify-between px-2 pb-1.5">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          Tool Permissions
        </h2>
        <span className="text-[10px] text-gray-500 font-mono truncate max-w-[9rem]" title={session.id}>
          {session.id.slice(0, 8)}…
        </span>
      </div>

      <div className="px-2 pb-2 text-[11px] leading-4 text-gray-500">
        Saved for this session in <span className="font-mono text-gray-400">$AUGENTIA_HOME/sessions/{session.id}/config.json</span>.
        Saving applies to the current live adapter immediately.
      </div>

      {loading ? (
        <p className="px-2 text-xs text-gray-600">Loading session config…</p>
      ) : (
        <>
          <textarea
            className="flex-1 min-h-0 w-full rounded-lg border border-gray-700 bg-gray-950 p-2 font-mono text-[11px] leading-4 text-gray-200 outline-none focus:border-indigo-500"
            spellCheck={false}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setSaved(false);
            }}
          />

          {error && (
            <div className="mt-2 rounded border border-red-800 bg-red-950/50 px-2 py-1.5 text-[11px] leading-4 text-red-200">
              {error}
            </div>
          )}
          {saved && !error && (
            <div className="mt-2 rounded border border-green-800 bg-green-950/40 px-2 py-1.5 text-[11px] text-green-200">
              Saved and applied to this session.
            </div>
          )}

          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={handleReset}
              disabled={saving}
              className="rounded border border-gray-700 bg-gray-900 px-2.5 py-1 text-xs text-gray-300 hover:border-gray-500 disabled:opacity-50"
            >
              Reset
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="rounded bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
