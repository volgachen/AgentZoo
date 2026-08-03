import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { PluginDefinition, PluginInstance, PluginLogLine } from "../../api/types";

interface Props {
  sessionId: string;
  plugin: PluginDefinition;
  instance: PluginInstance;
  onClose: () => void;
}

function formatLogTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString();
}

function responseData(response: Record<string, unknown> | null): unknown {
  if (!response) return null;
  return response.data ?? response;
}

function formatValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function formatStateData(response: Record<string, unknown> | null): string {
  const data = responseData(response);
  if (!data) return "No status loaded yet.";
  if (typeof data !== "object" || Array.isArray(data)) return formatValue(data);
  const entries = Object.entries(data as Record<string, unknown>);
  if (entries.length === 0) return "No status data.";
  const keyWidth = Math.max(...entries.map(([key]) => key.length));
  return entries
    .map(([key, value]) => `${key.padEnd(keyWidth)}: ${formatValue(value)}`)
    .join("\n");
}

function statusMessage(response: Record<string, unknown> | null): string {
  const data = responseData(response);
  if (!data || typeof data !== "object" || Array.isArray(data)) return "";
  const message = (data as Record<string, unknown>).message;
  return typeof message === "string" ? message : "";
}

export default function PluginSessionConsoleDialog({
  sessionId,
  plugin,
  instance,
  onClose,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [logs, setLogs] = useState<PluginLogLine[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadLogs = async () => {
    const nextLogs = await api.plugins.instanceLogs(instance.id, 300, sessionId);
    setLogs(nextLogs);
  };

  const loadStatus = async () => {
    const response = await api.plugins.command(instance.id, {
      command: "session_dialog.status",
      data: { session_id: sessionId },
    });
    setStatus(response);
  };

  const refresh = async () => {
    setError(null);
    try {
      await Promise.all([loadLogs(), loadStatus()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void loadLogs().catch((err) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
    }, 2000);
    return () => window.clearInterval(timer);
    // Intentionally refresh when the selected plugin/session changes.
  }, [instance.id, sessionId]);

  const sendInput = async () => {
    const text = input.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.plugins.command(instance.id, {
        command: "session_dialog.input",
        data: { session_id: sessionId, text },
      });
      setStatus(response);
      setInput("");
      await loadLogs();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="flex h-[80vh] w-full max-w-4xl flex-col rounded-xl border border-gray-700 bg-gray-900 shadow-2xl">
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <h2 className="text-lg font-semibold text-white">{plugin.name}</h2>
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-sm text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
          >
            Close
          </button>
        </div>

        <div className="px-5 py-2 text-xs">
          <pre className="max-h-24 overflow-auto whitespace-pre-wrap font-mono text-xs leading-4 text-gray-400">
            {formatStateData(status)}
          </pre>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-2 px-5 py-2">
          <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-gray-800 bg-gray-950">
            <div className="flex items-center justify-between border-b border-gray-800 px-3 py-2 text-xs font-medium text-gray-300">
              <span>Session logs</span>
              <button onClick={refresh} className="text-gray-400 hover:text-white">Refresh</button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-3 font-mono text-xs text-gray-300">
              {logs.length === 0 ? (
                <div className="text-gray-600">No session-scoped plugin logs yet.</div>
              ) : (
                logs.map((log, idx) => (
                  <div key={log.id ?? idx} className="whitespace-pre-wrap">
                    <span className="text-gray-600">{formatLogTime(log.ts)}</span>{" "}
                    <span className="text-gray-500">[{log.level ?? log.stream}]</span>{" "}
                    {log.line}
                  </div>
                ))
              )}
            </div>
          </div>

          {statusMessage(status) && (
            <div className="whitespace-pre-wrap text-xs leading-5 text-gray-400">
              {statusMessage(status)}
            </div>
          )}
        </div>

        {error && <div className="px-5 pb-2 text-xs text-red-300">{error}</div>}
        <div className="flex gap-2 px-5 pt-2 pb-4">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void sendInput();
            }}
            placeholder="Type plugin input for this session, for example: status"
            className="flex-1 rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-indigo-600"
          />
          <button
            onClick={sendInput}
            disabled={busy || !input.trim()}
            className="rounded bg-indigo-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? "Sending..." : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
