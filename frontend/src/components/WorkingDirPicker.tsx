import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { BrowseResponse } from "../api/client";

type Mode = "existing" | "template";

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: (value: { workingDir: string; templateDir: string | null }) => void;
}

interface BrowserState {
  data: BrowseResponse | null;
  loading: boolean;
  error: string | null;
}

function useBrowser(scope: "browse" | "templates", open: boolean) {
  const [state, setState] = useState<BrowserState>({ data: null, loading: false, error: null });

  const load = useCallback(
    async (path: string | null) => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const data =
          scope === "browse" ? await api.fs.browse(path) : await api.fs.templates(path);
        setState({ data, loading: false, error: null });
      } catch (e) {
        setState({ data: null, loading: false, error: (e as Error).message });
      }
    },
    [scope],
  );

  useEffect(() => {
    if (open) load(null);
  }, [open, load]);

  return { ...state, load };
}

function PathList({
  data,
  loading,
  error,
  selected,
  onSelect,
  onEnter,
  onGoParent,
}: {
  data: BrowseResponse | null;
  loading: boolean;
  error: string | null;
  selected: string | null;
  onSelect: (path: string) => void;
  onEnter: (path: string) => void;
  onGoParent: () => void;
}) {
  return (
    <div className="flex flex-col flex-1 min-h-0 border border-gray-700 rounded-lg bg-gray-900">
      <div className="px-3 py-2 border-b border-gray-700 flex items-center gap-2 text-xs">
        <button
          onClick={onGoParent}
          disabled={!data?.parent}
          className="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-gray-300"
          title="Parent directory"
        >
          ↑
        </button>
        <span className="font-mono text-gray-400 truncate" title={data?.path ?? ""}>
          {data?.path ?? "…"}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading && <div className="p-3 text-xs text-gray-500">Loading…</div>}
        {error && <div className="p-3 text-xs text-red-400 font-mono">{error}</div>}
        {!loading && !error && data && data.entries.length === 0 && (
          <div className="p-3 text-xs text-gray-500">No subdirectories.</div>
        )}
        {!loading && !error && data?.entries.map((e) => {
          const isSelected = selected === e.path;
          return (
            <button
              key={e.path}
              onClick={() => onSelect(e.path)}
              onDoubleClick={() => onEnter(e.path)}
              className={`w-full text-left px-3 py-1.5 text-sm font-mono border-b border-gray-800/50 last:border-0 transition-colors ${
                isSelected
                  ? "bg-indigo-900/60 text-indigo-100"
                  : "text-gray-300 hover:bg-gray-800/60"
              }`}
            >
              <span className="text-gray-500 mr-2">▸</span>
              {e.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function WorkingDirPicker({ open, onClose, onConfirm }: Props) {
  const [mode, setMode] = useState<Mode>("existing");
  const [selectedExisting, setSelectedExisting] = useState<string | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [targetDir, setTargetDir] = useState("");

  const existing = useBrowser("browse", open && mode === "existing");
  const templates = useBrowser("templates", open && mode === "template");

  useEffect(() => {
    if (!open) {
      setSelectedExisting(null);
      setSelectedTemplate(null);
      setTargetDir("");
      setMode("existing");
    }
  }, [open]);

  if (!open) return null;

  const canConfirm =
    mode === "existing"
      ? !!(selectedExisting || existing.data?.path)
      : !!selectedTemplate && targetDir.trim().length > 0;

  const handleConfirm = () => {
    if (mode === "existing") {
      const dir = selectedExisting ?? existing.data?.path ?? "";
      if (!dir) return;
      onConfirm({ workingDir: dir, templateDir: null });
    } else {
      if (!selectedTemplate || !targetDir.trim()) return;
      onConfirm({ workingDir: targetDir.trim(), templateDir: selectedTemplate });
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl h-[32rem] bg-gray-900 border border-gray-700 rounded-xl shadow-2xl flex flex-col">
        <div className="px-5 py-3 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Choose working directory</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-200 text-lg leading-none"
            title="Cancel"
          >
            ×
          </button>
        </div>

        <div className="px-5 pt-3 flex gap-1">
          {(["existing", "template"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1.5 rounded-t-lg text-sm transition-colors ${
                mode === m
                  ? "bg-gray-800 text-white"
                  : "text-gray-400 hover:text-white hover:bg-gray-800/40"
              }`}
            >
              {m === "existing" ? "Use existing directory" : "Copy from template"}
            </button>
          ))}
        </div>

        <div className="flex-1 min-h-0 px-5 pb-5 pt-2 flex flex-col gap-3">
          {mode === "existing" ? (
            <>
              <p className="text-xs text-gray-500">
                Pick any directory on this machine. The selected path (or the folder you're
                currently browsing, if nothing's highlighted) will be used as the working
                directory.
              </p>
              <PathList
                data={existing.data}
                loading={existing.loading}
                error={existing.error}
                selected={selectedExisting}
                onSelect={setSelectedExisting}
                onEnter={(p) => {
                  setSelectedExisting(null);
                  existing.load(p);
                }}
                onGoParent={() => existing.data?.parent && existing.load(existing.data.parent)}
              />
            </>
          ) : (
            <>
              <p className="text-xs text-gray-500">
                Pick a template under <code className="text-gray-400">templates/</code>. It will
                be copied to the target path you provide below. The target must not already
                exist.
              </p>
              <PathList
                data={templates.data}
                loading={templates.loading}
                error={templates.error}
                selected={selectedTemplate}
                onSelect={setSelectedTemplate}
                onEnter={(p) => {
                  setSelectedTemplate(p);
                  templates.load(p);
                }}
                onGoParent={() => templates.data?.parent && templates.load(templates.data.parent)}
              />
              <label className="text-xs text-gray-400 flex flex-col gap-1">
                Copy target (must not exist)
                <input
                  type="text"
                  className="bg-gray-950 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder-gray-600 font-mono focus:outline-none focus:border-indigo-500"
                  placeholder="/home/me/work/new-session-dir"
                  value={targetDir}
                  onChange={(e) => setTargetDir(e.target.value)}
                />
              </label>
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-700 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg text-sm text-gray-300 hover:bg-gray-800"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!canConfirm}
            className="px-3 py-1.5 rounded-lg text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}