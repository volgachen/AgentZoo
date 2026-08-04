import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AgentTemplate, Session } from "../api/types";

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

export default function ToolPermissionsPanel({ session }: { session: Session }) {
  const [agent, setAgent] = useState<AgentTemplate | null>(null);
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
    api.agents
      .get(session.agent_id)
      .then((nextAgent) => {
        if (cancelled) return;
        setAgent(nextAgent);
        setDraft(pretty(nextAgent.config?.tool_permissions ?? DEFAULT_TOOL_PERMISSIONS));
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
  }, [session.agent_id]);

  const handleSave = async () => {
    if (!agent) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const parsed = JSON.parse(draft) as unknown;
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("tool_permissions must be a JSON object");
      }
      const nextConfig = {
        ...(agent.config ?? {}),
        tool_permissions: parsed,
      };
      const updated = await api.agents.update(agent.id, { config: nextConfig });
      setAgent(updated);
      setDraft(pretty(updated.config?.tool_permissions ?? DEFAULT_TOOL_PERMISSIONS));
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setDraft(pretty(agent?.config?.tool_permissions ?? DEFAULT_TOOL_PERMISSIONS));
    setError(null);
    setSaved(false);
  };

  return (
    <section className="flex-1 flex flex-col min-h-0">
      <div className="shrink-0 flex items-center justify-between px-2 pb-1.5">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          Tool Permissions
        </h2>
        {agent && (
          <span className="text-[10px] text-gray-500 font-mono truncate max-w-[9rem]" title={agent.name}>
            {agent.name}
          </span>
        )}
      </div>

      <div className="px-2 pb-2 text-[11px] leading-4 text-gray-500">
        Saved on the agent template as <span className="font-mono text-gray-400">config.tool_permissions</span>.
        New turns in this session use the updated config after the backend adapter is restarted or rehydrated.
      </div>

      {loading ? (
        <p className="px-2 text-xs text-gray-600">Loading agent config…</p>
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
              Saved.
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
              disabled={saving || !agent}
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
