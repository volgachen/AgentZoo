import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { usePluginStore } from "../store/plugins";
import type { Plugin, PluginStatus } from "../api/types";

const STATUS_STYLE: Record<PluginStatus, string> = {
  stopped: "bg-gray-700 text-gray-300",
  running: "bg-green-900 text-green-300",
  exited: "bg-blue-900 text-blue-300",
  errored: "bg-red-900 text-red-300",
};

const STATUS_LABEL: Record<PluginStatus, string> = {
  stopped: "stopped",
  running: "running",
  exited: "exited",
  errored: "errored",
};

const SAMPLE_CODE = `import time

for i in range(10):
    print(f"hello {i}", flush=True)
    time.sleep(1)
`;

export default function PluginRegistry() {
  const plugins = usePluginStore((s) => s.plugins);
  const loaded = usePluginStore((s) => s.loaded);
  const loadPlugins = usePluginStore((s) => s.loadPlugins);
  const createPlugin = usePluginStore((s) => s.createPlugin);
  const startPlugin = usePluginStore((s) => s.startPlugin);
  const stopPlugin = usePluginStore((s) => s.stopPlugin);
  const restartPlugin = usePluginStore((s) => s.restartPlugin);
  const deletePlugin = usePluginStore((s) => s.deletePlugin);
  const navigate = useNavigate();

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCode, setNewCode] = useState(SAMPLE_CODE);
  const [submitting, setSubmitting] = useState(false);
  const [actionId, setActionId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    loadPlugins().catch((e) => setErr((e as Error).message));
  }, [loadPlugins]);

  const entries = Object.values(plugins).sort((a, b) =>
    a.plugin.created_at.localeCompare(b.plugin.created_at),
  );

  const onCreate = async () => {
    if (!newName.trim()) return;
    setSubmitting(true);
    setErr(null);
    try {
      await createPlugin(newName.trim(), newCode);
      setShowCreate(false);
      setNewName("");
      setNewCode(SAMPLE_CODE);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const wrap = async (id: string, fn: () => Promise<void>) => {
    setActionId(id);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setActionId(null);
    }
  };

  const onDelete = async (p: Plugin) => {
    if (!confirm(`Delete plugin "${p.name}"? This cannot be undone.`)) return;
    await wrap(p.id, () => deletePlugin(p.id));
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-white">Plugins</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium"
        >
          New plugin
        </button>
      </div>

      {err && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-900/40 border border-red-800 text-red-200 text-sm font-mono whitespace-pre-wrap">
          {err}
        </div>
      )}

      {!loaded ? (
        <div className="text-gray-400">Loading plugins…</div>
      ) : entries.length === 0 ? (
        <div className="text-gray-400 text-sm">
          No plugins yet. Click <span className="text-indigo-300">New plugin</span> to create one.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead>
              <tr className="text-gray-400 border-b border-gray-700">
                <th className="pb-3 pr-4 font-medium">Name</th>
                <th className="pb-3 pr-4 font-medium">Status</th>
                <th className="pb-3 pr-4 font-medium">Last exit</th>
                <th className="pb-3 pr-4 font-medium">Updated</th>
                <th className="pb-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(({ plugin: p }) => {
                const busy = actionId === p.id;
                return (
                  <tr
                    key={p.id}
                    className="border-b border-gray-800 hover:bg-gray-800/40"
                  >
                    <td className="py-3 pr-4 text-gray-200">
                      <div className="font-medium">{p.name}</div>
                      <div className="text-xs font-mono text-gray-500">
                        {p.id.slice(0, 8)}…
                      </div>
                    </td>
                    <td className="py-3 pr-4">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLE[p.status]}`}
                      >
                        {STATUS_LABEL[p.status]}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-gray-400 text-xs">
                      {p.last_exit_code === null
                        ? "—"
                        : `rc=${p.last_exit_code}`}
                      {p.last_error && (
                        <div
                          title={p.last_error}
                          className="text-red-400 truncate max-w-xs"
                        >
                          {p.last_error.split("\n").slice(-1)[0]}
                        </div>
                      )}
                    </td>
                    <td className="py-3 pr-4 text-gray-500 text-xs">
                      {new Date(p.updated_at).toLocaleString()}
                    </td>
                    <td className="py-3 flex flex-wrap gap-2">
                      {p.status === "running" ? (
                        <button
                          onClick={() => wrap(p.id, () => stopPlugin(p.id))}
                          disabled={busy}
                          className="px-3 py-1 rounded bg-gray-700 hover:bg-red-800 text-gray-200 text-xs disabled:opacity-50"
                        >
                          Stop
                        </button>
                      ) : (
                        <button
                          onClick={() => wrap(p.id, () => startPlugin(p.id))}
                          disabled={busy}
                          className="px-3 py-1 rounded bg-green-700 hover:bg-green-600 text-white text-xs disabled:opacity-50"
                        >
                          Start
                        </button>
                      )}
                      <button
                        onClick={() => wrap(p.id, () => restartPlugin(p.id))}
                        disabled={busy}
                        className="px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs disabled:opacity-50"
                      >
                        Restart
                      </button>
                      <button
                        onClick={() => navigate(`/plugins/${p.id}`)}
                        className="px-3 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white text-xs"
                      >
                        Open
                      </button>
                      <button
                        onClick={() => onDelete(p)}
                        disabled={busy || p.status === "running"}
                        className="px-3 py-1 rounded bg-gray-800 hover:bg-red-900 text-gray-400 hover:text-red-200 text-xs disabled:opacity-30"
                        title={p.status === "running" ? "Stop the plugin first" : ""}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={() => !submitting && setShowCreate(false)}
        >
          <div
            className="bg-gray-900 border border-gray-700 rounded-xl w-[640px] max-w-[95vw] p-5 flex flex-col gap-3"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold text-white">New plugin</h2>
            <label className="text-xs text-gray-400">Name</label>
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="my-watcher"
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
            />
            <label className="text-xs text-gray-400">Python code</label>
            <textarea
              value={newCode}
              onChange={(e) => setNewCode(e.target.value)}
              spellCheck={false}
              className="font-mono text-xs bg-gray-950 border border-gray-700 rounded px-3 py-2 text-gray-200 focus:outline-none focus:border-indigo-500 h-72 resize-none"
            />
            <p className="text-xs text-gray-500">
              Runs as <code>python -u &lt;file&gt;</code> with <code>cwd = backend/</code>. Stdout
              and stderr stream into the console.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowCreate(false)}
                disabled={submitting}
                className="px-3 py-1.5 rounded text-sm text-gray-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={onCreate}
                disabled={submitting || !newName.trim()}
                className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium"
              >
                {submitting ? "Creating…" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
