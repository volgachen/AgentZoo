import { useEffect, useMemo, useState } from "react";
import { ACTIVE_PLUGIN_STATUSES, usePluginStore } from "../store/plugins";
import type {
  PluginDefinition,
  PluginInstance,
  PluginRun,
  PluginStatus,
} from "../api/types";
import PluginLogDialog from "./PluginLogDialog";

const STATUS_STYLE: Record<PluginStatus, string> = {
  stopped: "bg-gray-700 text-gray-300",
  starting: "bg-yellow-900 text-yellow-200",
  waiting_input: "bg-purple-900 text-purple-200",
  running: "bg-green-900 text-green-300",
  stopping: "bg-yellow-900 text-yellow-200",
  exited: "bg-blue-900 text-blue-300",
  errored: "bg-red-900 text-red-300",
  cancelled: "bg-gray-800 text-gray-400",
};

interface InstanceFormState {
  id: string | null;
  plugin_id: string;
  display_name: string;
  auto_start: boolean;
  configText: string;
}

interface LogDialogState {
  instance: PluginInstance;
  run: PluginRun | null;
  mode: "live" | "history";
}

export default function PluginRegistry() {
  const catalog = usePluginStore((s) => s.catalog);
  const instances = usePluginStore((s) => s.instances);
  const runsByInstance = usePluginStore((s) => s.runsByInstance);
  const loaded = usePluginStore((s) => s.loaded);
  const loadPlugins = usePluginStore((s) => s.loadPlugins);
  const loadRuns = usePluginStore((s) => s.loadRuns);
  const createInstance = usePluginStore((s) => s.createInstance);
  const updateInstance = usePluginStore((s) => s.updateInstance);
  const deleteInstance = usePluginStore((s) => s.deleteInstance);
  const startInstance = usePluginStore((s) => s.startInstance);
  const stopInstance = usePluginStore((s) => s.stopInstance);
  const restartInstance = usePluginStore((s) => s.restartInstance);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [form, setForm] = useState<InstanceFormState | null>(null);
  const [logDialog, setLogDialog] = useState<LogDialogState | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    loadPlugins().catch((e) => setErr((e as Error).message));
  }, [loadPlugins]);

  useEffect(() => {
    if (expandedId) loadRuns(expandedId).catch((e) => setErr((e as Error).message));
  }, [expandedId, loadRuns]);

  const systemDefinitions = useMemo(
    () => catalog.filter((d) => d.scope === "system_side" || d.scope === "hybrid"),
    [catalog],
  );
  const definitionsById = useMemo(
    () => Object.fromEntries(catalog.map((d) => [d.id, d])),
    [catalog],
  );
  const instanceList = Object.values(instances).sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );

  const openCreate = (definition?: PluginDefinition) => {
    const selected = definition ?? systemDefinitions[0];
    if (!selected) return;
    setForm({
      id: null,
      plugin_id: selected.id,
      display_name: selected.name,
      auto_start: false,
      configText: JSON.stringify(selected.default_config ?? {}, null, 2),
    });
  };

  const openEdit = (instance: PluginInstance) => {
    setForm({
      id: instance.id,
      plugin_id: instance.plugin_id,
      display_name: instance.display_name,
      auto_start: instance.auto_start,
      configText: JSON.stringify(instance.config ?? {}, null, 2),
    });
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

  const onDelete = async (instance: PluginInstance) => {
    if (!confirm(`Delete plugin instance "${instance.display_name}"? This cannot be undone.`)) return;
    await wrap(instance.id, () => deleteInstance(instance.id));
    if (expandedId === instance.id) setExpandedId(null);
  };

  const saveForm = async () => {
    if (!form || !form.display_name.trim()) return;
    setSubmitting(true);
    setErr(null);
    try {
      const config = JSON.parse(form.configText || "{}");
      if (form.id) {
        await updateInstance(form.id, {
          display_name: form.display_name.trim(),
          auto_start: form.auto_start,
          config,
        });
      } else {
        await createInstance({
          plugin_id: form.plugin_id,
          display_name: form.display_name.trim(),
          auto_start: form.auto_start,
          config,
        });
      }
      setForm(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 overflow-y-auto">
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">System Plugins</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage system-side plugin instances, runs, and logs.
          </p>
        </div>
        <button
          onClick={() => openCreate()}
          disabled={systemDefinitions.length === 0}
          className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm font-medium"
        >
          Create instance
        </button>
      </div>

      {err && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-900/40 border border-red-800 text-red-200 text-sm font-mono whitespace-pre-wrap">
          {err}
        </div>
      )}

      <section className="mb-6 bg-gray-900/70 border border-gray-800 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-200">Installed system plugins</h2>
          <span className="text-xs text-gray-500">{systemDefinitions.length} available</span>
        </div>
        {systemDefinitions.length === 0 ? (
          <p className="text-sm text-gray-500">No system-side plugin definitions found.</p>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {systemDefinitions.map((d) => (
              <div key={d.id} className="border border-gray-800 rounded-lg p-3 bg-gray-950/60">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium text-gray-100 truncate">{d.name}</div>
                    <div className="text-xs text-gray-500 font-mono truncate">
                      {d.id} · v{d.version} · {d.scope}
                    </div>
                  </div>
                  <button
                    onClick={() => openCreate(d)}
                    className="shrink-0 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs"
                  >
                    Create
                  </button>
                </div>
                {d.description && <p className="mt-2 text-xs text-gray-500 line-clamp-2">{d.description}</p>}
                <div className="mt-2 flex flex-wrap gap-1">
                  {d.capabilities.slice(0, 5).map((cap) => (
                    <span key={cap} className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 text-[11px]">
                      {cap}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="bg-gray-900/70 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-200">Plugin instances</h2>
          <span className="text-xs text-gray-500">{instanceList.length} instances</span>
        </div>

        {!loaded ? (
          <div className="p-4 text-gray-400">Loading plugins...</div>
        ) : instanceList.length === 0 ? (
          <div className="p-4 text-gray-500 text-sm">No plugin instances yet.</div>
        ) : (
          <table className="w-full text-sm text-left">
            <thead>
              <tr className="text-gray-400 border-b border-gray-800">
                <th className="px-4 py-3 font-medium">Instance</th>
                <th className="px-4 py-3 font-medium">Plugin</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Auto start</th>
                <th className="px-4 py-3 font-medium">Updated</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {instanceList.map((instance) => {
                const definition = definitionsById[instance.plugin_id];
                const active = ACTIVE_PLUGIN_STATUSES.has(instance.status);
                const busy = actionId === instance.id;
                const expanded = expandedId === instance.id;
                return (
                  <FragmentRow
                    key={instance.id}
                    instance={instance}
                    definition={definition}
                    expanded={expanded}
                    busy={busy}
                    active={active}
                    runs={runsByInstance[instance.id] ?? []}
                    onToggle={() => setExpandedId(expanded ? null : instance.id)}
                    onStart={() => wrap(instance.id, () => startInstance(instance.id))}
                    onStop={() => wrap(instance.id, () => stopInstance(instance.id))}
                    onRestart={() => wrap(instance.id, () => restartInstance(instance.id))}
                    onEdit={() => openEdit(instance)}
                    onDelete={() => onDelete(instance)}
                    onLiveLogs={() => setLogDialog({ instance, run: null, mode: "live" })}
                    onRunLogs={(run) => setLogDialog({ instance, run, mode: "history" })}
                  />
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {form && (
        <InstanceFormDialog
          form={form}
          definitions={systemDefinitions}
          submitting={submitting}
          onChange={setForm}
          onCancel={() => setForm(null)}
          onSave={saveForm}
        />
      )}

      {logDialog && (
        <PluginLogDialog
          instance={logDialog.instance}
          run={logDialog.run}
          mode={logDialog.mode}
          onClose={() => setLogDialog(null)}
        />
      )}
    </div>
  );
}

function FragmentRow({
  instance,
  definition,
  expanded,
  busy,
  active,
  runs,
  onToggle,
  onStart,
  onStop,
  onRestart,
  onEdit,
  onDelete,
  onLiveLogs,
  onRunLogs,
}: {
  instance: PluginInstance;
  definition?: PluginDefinition;
  expanded: boolean;
  busy: boolean;
  active: boolean;
  runs: PluginRun[];
  onToggle: () => void;
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onLiveLogs: () => void;
  onRunLogs: (run: PluginRun) => void;
}) {
  return (
    <>
      <tr className="border-b border-gray-800 hover:bg-gray-800/40">
        <td className="px-4 py-3 text-gray-200">
          <button onClick={onToggle} className="mr-2 text-gray-500 hover:text-gray-200">
            {expanded ? "▾" : "▸"}
          </button>
          <span className="font-medium">{instance.display_name}</span>
          <div className="text-xs text-gray-500 font-mono ml-6">{instance.id.slice(0, 8)}...</div>
        </td>
        <td className="px-4 py-3 text-gray-400">
          <div>{definition?.name ?? instance.plugin_id}</div>
          <div className="text-xs text-gray-600 font-mono">{instance.plugin_id}</div>
        </td>
        <td className="px-4 py-3">
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLE[instance.status]}`}>
            {instance.status}
          </span>
        </td>
        <td className="px-4 py-3 text-gray-400">{instance.auto_start ? "yes" : "no"}</td>
        <td className="px-4 py-3 text-gray-500 text-xs">{new Date(instance.updated_at).toLocaleString()}</td>
        <td className="px-4 py-3">
          <div className="flex flex-wrap gap-2">
            {active ? (
              <button onClick={onStop} disabled={busy} className="px-2.5 py-1 rounded bg-gray-700 hover:bg-red-800 text-gray-200 text-xs disabled:opacity-50">
                Stop
              </button>
            ) : (
              <button onClick={onStart} disabled={busy} className="px-2.5 py-1 rounded bg-green-700 hover:bg-green-600 text-white text-xs disabled:opacity-50">
                Start
              </button>
            )}
            <button onClick={onRestart} disabled={busy} className="px-2.5 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs disabled:opacity-50">
              Restart
            </button>
            <button onClick={onEdit} disabled={active} className="px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs disabled:opacity-30">
              Edit
            </button>
            <button onClick={onLiveLogs} className="px-2.5 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white text-xs">
              Logs
            </button>
            <button onClick={onDelete} disabled={active || busy} className="px-2.5 py-1 rounded bg-gray-800 hover:bg-red-900 text-gray-400 hover:text-red-200 text-xs disabled:opacity-30">
              Delete
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-gray-800 bg-gray-950/60">
          <td colSpan={6} className="px-10 py-4">
            <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-4">
              <div>
                <h3 className="text-xs font-semibold text-gray-400 mb-2">Config summary</h3>
                <pre className="max-h-44 overflow-auto rounded bg-gray-950 border border-gray-800 p-3 text-xs text-gray-400 whitespace-pre-wrap">
                  {JSON.stringify(instance.config ?? {}, null, 2)}
                </pre>
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-semibold text-gray-400">Recent runs</h3>
                  <button onClick={onLiveLogs} className="text-xs text-indigo-300 hover:text-indigo-200">
                    View live logs
                  </button>
                </div>
                {runs.length === 0 ? (
                  <p className="text-xs text-gray-600">No runs loaded.</p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {runs.slice(0, 5).map((run) => (
                      <div key={run.id} className="rounded border border-gray-800 bg-gray-900/60 px-3 py-2">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <span className={`mr-2 px-1.5 py-0.5 rounded text-[11px] ${STATUS_STYLE[run.status]}`}>{run.status}</span>
                            <span className="text-xs text-gray-500 font-mono">{run.id.slice(0, 8)}...</span>
                            {run.exit_code !== null && <span className="ml-2 text-xs text-gray-500">rc={run.exit_code}</span>}
                          </div>
                          <button onClick={() => onRunLogs(run)} className="text-xs text-indigo-300 hover:text-indigo-200">
                            View logs
                          </button>
                        </div>
                        <div className="mt-1 text-xs text-gray-600">
                          started {formatTime(run.started_at ?? run.created_at)}
                          {run.exited_at ? ` · exited ${formatTime(run.exited_at)}` : ""}
                        </div>
                        {run.error && <div className="mt-1 text-xs text-red-300 truncate">{run.error.split("\n").slice(-1)[0]}</div>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function InstanceFormDialog({
  form,
  definitions,
  submitting,
  onChange,
  onCancel,
  onSave,
}: {
  form: InstanceFormState;
  definitions: PluginDefinition[];
  submitting: boolean;
  onChange: (form: InstanceFormState) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const editing = form.id !== null;
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-[700px] max-w-[96vw] p-5 flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-white">{editing ? "Edit plugin instance" : "Create plugin instance"}</h2>
        <label className="text-xs text-gray-400">Plugin</label>
        <select
          value={form.plugin_id}
          disabled={editing}
          onChange={(e) => {
            const definition = definitions.find((d) => d.id === e.target.value);
            onChange({
              ...form,
              plugin_id: e.target.value,
              display_name: definition?.name ?? form.display_name,
              configText: JSON.stringify(definition?.default_config ?? {}, null, 2),
            });
          }}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-indigo-500 disabled:opacity-60"
        >
          {definitions.map((d) => (
            <option key={d.id} value={d.id}>{d.name} ({d.id})</option>
          ))}
        </select>
        <label className="text-xs text-gray-400">Display name</label>
        <input
          value={form.display_name}
          onChange={(e) => onChange({ ...form, display_name: e.target.value })}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
        />
        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={form.auto_start}
            onChange={(e) => onChange({ ...form, auto_start: e.target.checked })}
          />
          Auto start on backend startup
        </label>
        <label className="text-xs text-gray-400">Config JSON</label>
        <textarea
          value={form.configText}
          onChange={(e) => onChange({ ...form, configText: e.target.value })}
          spellCheck={false}
          className="font-mono text-xs bg-gray-950 border border-gray-700 rounded px-3 py-2 text-gray-200 focus:outline-none focus:border-indigo-500 h-72 resize-none"
        />
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onCancel} disabled={submitting} className="px-3 py-1.5 rounded text-sm text-gray-400 hover:text-white">
            Cancel
          </button>
          <button onClick={onSave} disabled={submitting || !form.display_name.trim()} className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium">
            {submitting ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}
