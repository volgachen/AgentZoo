import { useEffect, useRef, useState } from "react";
import { usePluginStore } from "../store/plugins";
import type { PluginInstance, PluginLogLine, PluginRun } from "../api/types";

const EMPTY_LOGS: PluginLogLine[] = [];

const LINE_STYLE: Record<PluginLogLine["stream"], string> = {
  stdout: "text-gray-200",
  stderr: "text-red-300",
  system: "text-gray-500 italic",
  plugin: "text-indigo-200",
};

interface Props {
  instance: PluginInstance;
  run: PluginRun | null;
  mode: "live" | "history";
  onClose: () => void;
}

export default function PluginLogDialog({ instance, run, mode, onClose }: Props) {
  const liveLogs = usePluginStore((s) => s.logsByInstance[instance.id] ?? EMPTY_LOGS);
  const subscribe = usePluginStore((s) => s.subscribe);
  const unsubscribe = usePluginStore((s) => s.unsubscribe);
  const loadInstanceLogs = usePluginStore((s) => s.loadInstanceLogs);
  const loadRunLogs = usePluginStore((s) => s.loadRunLogs);

  const [historyLogs, setHistoryLogs] = useState<PluginLogLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [autoscroll, setAutoscroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const runId = run?.id ?? null;

  useEffect(() => {
    setErr(null);
    if (mode === "live") {
      setLoading(true);
      loadInstanceLogs(instance.id, 500)
        .then(() => subscribe(instance.id))
        .catch((e) => setErr((e as Error).message))
        .finally(() => setLoading(false));
      return () => unsubscribe(instance.id);
    }

    if (!runId) return;
    setLoading(true);
    loadRunLogs(runId, 1000)
      .then(setHistoryLogs)
      .catch((e) => setErr((e as Error).message))
      .finally(() => setLoading(false));
  }, [instance.id, loadInstanceLogs, loadRunLogs, mode, runId, subscribe, unsubscribe]);

  const logs = mode === "live" ? liveLogs : historyLogs;

  useEffect(() => {
    if (autoscroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length, autoscroll]);

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-950 border border-gray-700 rounded-lg w-[980px] max-w-[96vw] h-[78vh] flex flex-col shadow-2xl">
        <div className="shrink-0 px-4 py-3 border-b border-gray-800 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-white truncate">{instance.display_name}</h2>
            <p className="text-xs text-gray-500 font-mono truncate">
              {mode === "live" ? "Live instance logs" : `Run ${run?.id ?? ""}`}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
              <input
                type="checkbox"
                checked={autoscroll}
                onChange={(e) => setAutoscroll(e.target.checked)}
              />
              autoscroll
            </label>
            <button
              onClick={onClose}
              className="px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs"
            >
              Close
            </button>
          </div>
        </div>

        {err && (
          <div className="mx-4 mt-3 px-3 py-2 rounded bg-red-950/50 border border-red-900 text-red-200 text-xs font-mono whitespace-pre-wrap">
            {err}
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4 font-mono text-xs flex flex-col gap-0.5">
          {loading && logs.length === 0 ? (
            <p className="text-gray-500">Loading logs...</p>
          ) : logs.length === 0 ? (
            <p className="text-gray-600">No logs.</p>
          ) : (
            logs.map((ln, i) => (
              <div key={`${ln.ts}-${i}`} className={`grid grid-cols-[156px_64px_minmax(0,1fr)] gap-3 ${LINE_STYLE[ln.stream]}`}>
                <span className="text-gray-600">{new Date(ln.ts).toLocaleString()}</span>
                <span className="text-gray-500">{ln.stream}</span>
                <span className="whitespace-pre-wrap break-words">{ln.line}</span>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
