import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { BrowseResponse } from "../api/client";
import type { SessionCreateMode } from "../api/types";

interface Props {
  open: boolean;
  launching?: boolean;
  agentName?: string;
  onClose: () => void;
  onConfirm: (value: {
    sourceDir: string;
    createMode: SessionCreateMode;
    sessionName: string | null;
    additionalPrompt: string | null;
    additionalPromptPath: string | null;
  }) => void;
}

interface BrowserState {
  data: BrowseResponse | null;
  loading: boolean;
  error: string | null;
}

const MODE_OPTIONS: Array<{
  value: SessionCreateMode;
  label: string;
  description: string;
}> = [
  {
    value: "use_existing_directory",
    label: "Use Existing Directory",
    description: "Start the session directly in the selected folder.",
  },
  {
    value: "duplicate_by_copy",
    label: "Duplicate by Copy",
    description: "Copy the selected folder into AUGENTIA_WORKTREE_ROOT and work there.",
  },
  {
    value: "git_worktree",
    label: "Work in Git Worktree",
    description: "Create a Git worktree under AUGENTIA_WORKTREE_ROOT from the selected repository.",
  },
];

function useBrowser(open: boolean) {
  const [state, setState] = useState<BrowserState>({ data: null, loading: false, error: null });

  const load = useCallback(async (path: string | null) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await api.fs.browse(path);
      setState({ data, loading: false, error: null });
    } catch (e) {
      setState({ data: null, loading: false, error: (e as Error).message });
    }
  }, []);

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
    <div className="flex flex-col min-h-[12rem] border border-gray-700 rounded-lg bg-gray-900">
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

export default function WorkingDirPicker({
  open,
  launching = false,
  agentName,
  onClose,
  onConfirm,
}: Props) {
  const [selectedDir, setSelectedDir] = useState<string | null>(null);
  const [createMode, setCreateMode] = useState<SessionCreateMode>("use_existing_directory");
  const [sessionName, setSessionName] = useState("");
  const [promptText, setPromptText] = useState("");
  const [promptPath, setPromptPath] = useState("");

  const browser = useBrowser(open);

  useEffect(() => {
    if (!open) {
      setSelectedDir(null);
      setCreateMode("use_existing_directory");
      setSessionName("");
      setPromptText("");
      setPromptPath("");
    }
  }, [open]);

  if (!open) return null;

  const effectiveDir = selectedDir ?? browser.data?.path ?? "";
  const canConfirm = !!effectiveDir && !launching;

  const handleConfirm = () => {
    if (!effectiveDir) return;
    onConfirm({
      sourceDir: effectiveDir,
      createMode,
      sessionName: sessionName.trim() ? sessionName.trim() : null,
      additionalPrompt: promptText.trim() ? promptText : null,
      additionalPromptPath: promptPath.trim() ? promptPath.trim() : null,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl h-[44rem] max-h-[92vh] bg-gray-900 border border-gray-700 rounded-xl shadow-2xl flex flex-col">
        <div className="px-5 py-3 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">
            Launch{agentName ? ` ${agentName}` : " Session"}
          </h2>
          <button
            onClick={onClose}
            disabled={launching}
            className="text-gray-500 hover:text-gray-200 disabled:opacity-40 text-lg leading-none"
            title="Cancel"
          >
            ×
          </button>
        </div>

        <div className="flex-1 min-h-0 px-5 py-4 flex flex-col gap-4 overflow-y-auto">
          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                  1. Select source directory
                </h3>
                <p className="text-xs text-gray-500">
                  Select a folder, or use the folder currently shown in the browser.
                </p>
              </div>
              <div className="text-xs font-mono text-gray-500 truncate max-w-xs" title={effectiveDir}>
                {effectiveDir || "No directory selected"}
              </div>
            </div>
            <PathList
              data={browser.data}
              loading={browser.loading}
              error={browser.error}
              selected={selectedDir}
              onSelect={setSelectedDir}
              onEnter={(p) => {
                setSelectedDir(null);
                browser.load(p);
              }}
              onGoParent={() => browser.data?.parent && browser.load(browser.data.parent)}
            />
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
              2. Choose creation mode
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {MODE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  onClick={() => setCreateMode(option.value)}
                  className={`text-left border rounded-lg px-3 py-2 transition-colors ${
                    createMode === option.value
                      ? "border-indigo-500 bg-indigo-950/50"
                      : "border-gray-700 bg-gray-950 hover:border-gray-600"
                  }`}
                >
                  <div className="text-sm text-gray-100">{option.label}</div>
                  <div className="mt-1 text-xs text-gray-500">{option.description}</div>
                </button>
              ))}
            </div>
            {createMode !== "use_existing_directory" && (
              <p className="text-xs text-gray-500">
                The working folder will be created automatically under AUGENTIA_WORKTREE_ROOT.
              </p>
            )}
          </section>

          <label className="text-xs text-gray-400 flex flex-col gap-1">
            <span className="font-semibold uppercase tracking-wide">3. Session name (optional)</span>
            <input
              type="text"
              className="bg-gray-950 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
              placeholder="Use default name if blank"
              value={sessionName}
              onChange={(e) => setSessionName(e.target.value)}
            />
          </label>

          <label className="text-xs text-gray-400 flex flex-col gap-1">
            <span>
              Additional system prompt (optional) — appended after the agent's base system prompt
            </span>
            <textarea
              className="bg-gray-950 border border-gray-700 rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-600 font-mono focus:outline-none focus:border-indigo-500 resize-none h-20"
              placeholder={`Focus on Python performance optimization.\nPrefer pytest over unittest.`}
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
            />
          </label>

          <label className="text-xs text-gray-400 flex flex-col gap-1">
            <span>
              Additional prompt file path (optional) — server-side path; contents appended after the inline text above
            </span>
            <input
              type="text"
              className="bg-gray-950 border border-gray-700 rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-600 font-mono focus:outline-none focus:border-indigo-500"
              placeholder="/path/to/extra-prompt.md"
              value={promptPath}
              onChange={(e) => setPromptPath(e.target.value)}
            />
          </label>
        </div>

        <div className="px-5 py-3 border-t border-gray-700 flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={launching}
            className="px-3 py-1.5 rounded-lg text-sm text-gray-300 hover:bg-gray-800 disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!canConfirm}
            className="px-3 py-1.5 rounded-lg text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white"
          >
            {launching ? "Launching..." : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
