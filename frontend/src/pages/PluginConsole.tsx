import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { usePluginStore } from "../store/plugins";
import type { PluginLogLine, PluginStatus } from "../api/types";

const STATUS_STYLE: Record<PluginStatus, string> = {
  stopped: "bg-gray-700 text-gray-300",
  running: "bg-green-900 text-green-300",
  exited: "bg-blue-900 text-blue-300",
  errored: "bg-red-900 text-red-300",
};

const LINE_STYLE: Record<PluginLogLine["stream"], string> = {
  stdout: "text-gray-200",
  stderr: "text-red-300",
  system: "text-gray-500 italic",
};

export default function PluginConsole() {
  const { pluginId } = useParams<{ pluginId: string }>();
  const navigate = useNavigate();
  const entry = usePluginStore((s) => (pluginId ? s.plugins[pluginId] : undefined));
  const subscribe = usePluginStore((s) => s.subscribe);
  const unsubscribe = usePluginStore((s) => s.unsubscribe);
  const startPlugin = usePluginStore((s) => s.startPlugin);
  const stopPlugin = usePluginStore((s) => s.stopPlugin);
  const restartPlugin = usePluginStore((s) => s.restartPlugin);
  const updatePlugin = usePluginStore((s) => s.updatePlugin);
  const clearLogs = usePluginStore((s) => s.clearLogs);

  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editCode, setEditCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [autoscroll, setAutoscroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!pluginId) return;
    subscribe(pluginId).catch((e) => setErr((e as Error).message));
    return () => {
      unsubscribe(pluginId);
    };
  }, [pluginId, subscribe, unsubscribe]);

  useEffect(() => {
    if (autoscroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entry?.logs.length, autoscroll]);

  if (!pluginId) return null;
  if (!entry) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-gray-400">
        <p>Loading plugin…</p>
      </div>
    );
  }

  const { plugin, logs } = entry;
  const running = plugin.status === "running";

  const wrap = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const beginEdit = () => {
    setEditName(plugin.name);
    setEditCode(plugin.code);
    setEditing(true);
  };

  const saveEdit = async () => {
    await wrap(() =>
      updatePlugin(plugin.id, { name: editName, code: editCode }),
    );
    setEditing(false);
  };

  return (
    <div className="flex flex-col h-full p-4 gap-3 min-h-0">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={() => navigate("/plugins")}
            className="text-gray-400 hover:text-white text-sm"
            title="Back to plugins"
          >
            ←
          </button>
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-white truncate">
              {plugin.name}
            </h1>
            <p className="text-xs text-gray-500 font-mono truncate">{plugin.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLE[plugin.status]}`}
          >
            {plugin.status}
          </span>
          {plugin.last_exit_code !== null && (
            <span className="text-xs text-gray-500">rc={plugin.last_exit_code}</span>
          )}
          {running ? (
            <button
              onClick={() => wrap(() => stopPlugin(plugin.id))}
              disabled={busy}
              className="px-3 py-1 rounded bg-gray-700 hover:bg-red-800 text-gray-200 text-xs disabled:opacity-50"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={() => wrap(() => startPlugin(plugin.id))}
              disabled={busy}
              className="px-3 py-1 rounded bg-green-700 hover:bg-green-600 text-white text-xs disabled:opacity-50"
            >
              Start
            </button>
          )}
          <button
            onClick={() => wrap(() => restartPlugin(plugin.id))}
            disabled={busy}
            className="px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs disabled:opacity-50"
          >
            Restart
          </button>
        </div>
      </div>

      {err && (
        <div className="px-3 py-2 rounded-lg bg-red-900/40 border border-red-800 text-red-200 text-xs font-mono whitespace-pre-wrap">
          {err}
        </div>
      )}
      {plugin.last_error && plugin.status === "errored" && (
        <div className="px-3 py-2 rounded-lg bg-red-950/50 border border-red-900 text-red-200 text-xs font-mono whitespace-pre-wrap">
          {plugin.last_error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 flex-1 min-h-0">
        {/* Code panel */}
        <div className="flex flex-col bg-gray-900 border border-gray-700 rounded-xl min-h-0">
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
            <span className="text-xs text-gray-400">Source</span>
            {editing ? (
              <div className="flex gap-2">
                <button
                  onClick={() => setEditing(false)}
                  disabled={busy}
                  className="px-2 py-0.5 rounded text-xs text-gray-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={saveEdit}
                  disabled={busy || !editName.trim()}
                  className="px-2 py-0.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs"
                >
                  Save
                </button>
              </div>
            ) : (
              <button
                onClick={beginEdit}
                disabled={running}
                title={running ? "Stop the plugin to edit code" : ""}
                className="px-2 py-0.5 rounded text-xs text-indigo-300 hover:text-indigo-200 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Edit
              </button>
            )}
          </div>
          {editing ? (
            <div className="flex flex-col gap-2 p-3 flex-1 min-h-0">
              <input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
              />
              <textarea
                value={editCode}
                onChange={(e) => setEditCode(e.target.value)}
                spellCheck={false}
                className="flex-1 font-mono text-xs bg-gray-950 border border-gray-700 rounded px-3 py-2 text-gray-200 focus:outline-none focus:border-indigo-500 resize-none"
              />
            </div>
          ) : (
            <pre className="flex-1 overflow-auto p-3 font-mono text-xs text-gray-300 whitespace-pre">
              {plugin.code || <span className="text-gray-600">(empty)</span>}
            </pre>
          )}
        </div>

        {/* Logs panel */}
        <div className="flex flex-col bg-gray-900 border border-gray-700 rounded-xl min-h-0">
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
            <span className="text-xs text-gray-400">
              Console <span className="text-gray-600">({logs.length} lines)</span>
            </span>
            <div className="flex gap-3 items-center">
              <label className="flex items-center gap-1 text-xs text-gray-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoscroll}
                  onChange={(e) => setAutoscroll(e.target.checked)}
                />
                autoscroll
              </label>
              <button
                onClick={() => wrap(() => clearLogs(plugin.id))}
                className="text-xs text-gray-400 hover:text-white"
              >
                Clear
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-3 font-mono text-xs flex flex-col gap-0.5">
            {logs.length === 0 ? (
              <p className="text-gray-600">No output yet.</p>
            ) : (
              logs.map((ln, i) => (
                <div
                  key={i}
                  className={`whitespace-pre-wrap break-all ${LINE_STYLE[ln.stream]}`}
                >
                  {ln.line}
                </div>
              ))
            )}
            <div ref={bottomRef} />
          </div>
        </div>
      </div>
    </div>
  );
}
