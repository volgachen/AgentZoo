import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useStore } from "../store/sessions";
import type { StreamEvent } from "../api/types";
import TaskListPanel from "../components/TaskListPanel";
import SubAgentListPanel from "../components/SubAgentListPanel";
import ActiveSessionsMenu from "../components/ActiveSessionsMenu";

const EVENT_STYLE: Record<string, string> = {
  text: "text-gray-200",
  tool_call: "text-yellow-400",
  tool_confirm: "text-orange-400",
  tool_result: "text-amber-300",
  status: "text-blue-400",
  error: "text-red-400",
  done: "text-green-500",
  session_state: "text-gray-500",
  agent_message: "text-gray-200",
  user: "text-indigo-300",
};

// Build a one-line summary + a fully-formatted block for tool events. The raw
// payload is JSON: tool_call = {name,args}, tool_result = {name,result}.
function formatToolData(
  type: string,
  raw: string,
): { summary: string; full: string } {
  try {
    const obj = JSON.parse(raw);
    if (type === "tool_call" || type === "tool_confirm") {
      const args = obj.args ?? {};
      const argsLine = JSON.stringify(args);
      const argsBlock = JSON.stringify(args, null, 2);
      return {
        summary: `${obj.name}(${argsLine})`,
        full: `${obj.name}(\n${argsBlock}\n)`,
      };
    }
    if (type === "tool_result") {
      const result = obj.result;
      const resultLine =
        typeof result === "string" ? result : JSON.stringify(result);
      const resultBlock =
        typeof result === "string" ? result : JSON.stringify(result, null, 2);
      return {
        summary: `${obj.name} → ${resultLine}`,
        full: `${obj.name} →\n${resultBlock}`,
      };
    }
  } catch {
    // fall through to raw
  }
  return { summary: raw, full: raw };
}

// Collapse multi-line text to a single line with a visible ↵ marker so the user
// can tell something was truncated.
function toOneLine(s: string, max = 200): string {
  const flat = s.replace(/\s+/g, " ").trim();
  return flat.length > max ? flat.slice(0, max) + "…" : flat;
}

function ToolEventLine({ event }: { event: StreamEvent }) {
  const [expanded, setExpanded] = useState(false);
  const style = EVENT_STYLE[event.type] ?? "text-gray-300";
  const prefix =
    event.type === "tool_call" ? "⚙ " : event.type === "tool_confirm" ? "⚠ " : "↩ ";
  const { summary, full } = formatToolData(event.type, event.data);
  const oneLine = toOneLine(summary);
  const chevron = expanded ? "▾" : "▸";
  return (
    <div className={`text-left font-mono text-sm ${style}`}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left flex items-start gap-1 hover:bg-gray-800/40 rounded px-1 -mx-1 cursor-pointer"
        title={expanded ? "Collapse" : "Expand"}
      >
        <span className="text-gray-500 select-none">{chevron}</span>
        <span className="flex-1 truncate">
          {prefix}
          {oneLine}
        </span>
      </button>
      {expanded && (
        <pre className="mt-1 ml-4 px-2 py-1.5 bg-gray-950/60 border border-gray-800 rounded whitespace-pre-wrap break-all text-xs text-gray-300">
          {full}
        </pre>
      )}
    </div>
  );
}

function EventLine({ event }: { event: StreamEvent }) {
  if (
    event.type === "tool_call" ||
    event.type === "tool_confirm" ||
    event.type === "tool_result"
  ) {
    return <ToolEventLine event={event} />;
  }
  const style = EVENT_STYLE[event.type] ?? "text-gray-300";
  const prefix =
    event.type === "status"
      ? "● "
      : event.type === "error"
        ? "✗ "
        : event.type === "done"
          ? "✓ "
          : event.type === "user"
            ? "❯ "
            : "";
  const body =
    typeof event.data === "string" ? event.data : JSON.stringify(event.data);
  return (
    <div className={`text-left font-mono text-sm whitespace-pre-wrap break-all ${style}`}>
      {prefix}
      {body}
    </div>
  );
}

export default function LiveConsole() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const sessions = useStore((s) => s.sessions);
  const sendMessage = useStore((s) => s.sendMessage);
  const resolveConfirm = useStore((s) => s.resolveConfirm);
  const openSession = useStore((s) => s.openSession);
  const fetchTasks = useStore((s) => s.fetchTasks);
  const hydrateSessions = useStore((s) => s.hydrateSessions);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const entry = sessionId ? sessions[sessionId] : undefined;

  // Child sessions (sub-agents) are just sessions whose parent is this one.
  // They land in the store via hydrateSessions, so we filter the live map.
  const children = Object.values(sessions)
    .map((e) => e.session)
    .filter((s) => s.parent_session_id === sessionId);

  const eventCount = entry?.events.length ?? 0;

  // Reactive refresh: tasks only change via task_* tool calls, which surface as
  // stream events — so refetch tasks (and re-hydrate to catch newly spawned
  // sub-agents) whenever the event count moves.
  useEffect(() => {
    if (!sessionId) return;
    fetchTasks(sessionId).catch(() => {});
    hydrateSessions().catch(() => {});
  }, [sessionId, eventCount, fetchTasks, hydrateSessions]);

  // Backup poll: covers changes that emit no event on this socket — e.g. a
  // sub-agent spawned from another tab, or its status flipping as it works.
  useEffect(() => {
    if (!sessionId) return;
    const timer = setInterval(() => {
      fetchTasks(sessionId).catch(() => {});
      hydrateSessions().catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [sessionId, fetchTasks, hydrateSessions]);

  // Backfill history + attach a live socket when viewing a session we didn't
  // launch in this tab (e.g. subagent-spawned). No-op if already live.
  useEffect(() => {
    if (sessionId) openSession(sessionId);
  }, [sessionId, openSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entry?.events.length, entry?.generating]);

  if (!entry) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-gray-400">
        <p>Session not found.</p>
        <button
          onClick={() => navigate("/")}
          className="text-indigo-400 hover:text-indigo-300 text-sm underline"
        >
          Back to registry
        </button>
      </div>
    );
  }

  const { session, events } = entry;
  const generating = entry.generating;

  const handleSend = () => {
    const msg = input.trim();
    if (!msg || !sessionId || generating) return;
    sendMessage(sessionId, msg);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-white">Live Console</h1>
          <p className="text-xs text-gray-500 font-mono">{session.id}</p>
          <p className="text-xs text-gray-500 font-mono">
            <span className="text-gray-600">cwd: </span>
            {session.working_dir ?? "—"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ActiveSessionsMenu currentSessionId={sessionId} />
          {generating ? (
            <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-900/60 text-indigo-200">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-300 animate-pulse" />
              generating…
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-800 text-gray-400">
              idle
            </span>
          )}
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              session.status === "RUNNING"
                ? "bg-green-900 text-green-300"
                : session.status === "ERROR"
                  ? "bg-red-900 text-red-300"
                  : session.status === "WAITING_CONFIRM"
                    ? "bg-orange-900 text-orange-300"
                    : session.status === "WAITING_USER"
                      ? "bg-blue-900 text-blue-300"
                      : "bg-gray-700 text-gray-400"
            }`}
          >
            {session.status}
          </span>
        </div>
      </div>

      {/* Body: event log + status sidebar */}
      <div className="flex-1 flex gap-3 min-h-0">
        {/* Event log */}
        <div className="flex-1 bg-gray-900 rounded-xl border border-gray-700 p-4 overflow-y-auto flex flex-col gap-1 min-h-0">
          {events.length === 0 && (
            <p className="text-gray-600 text-sm font-mono">Waiting for output…</p>
          )}
          {events.map((ev, i) => (
            <EventLine key={i} event={ev} />
          ))}
          {generating && (
            <div className="flex items-center gap-2 font-mono text-sm text-indigo-300">
              <span className="inline-block w-3.5 h-3.5 rounded-full border-2 border-indigo-400/40 border-t-indigo-300 animate-spin" />
              <span className="text-gray-500">generating…</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Status sidebar: tasks + sub-agents (hidden on narrow screens) */}
        <aside className="hidden lg:flex w-80 shrink-0 flex-col gap-3 min-h-0">
          <div className="flex-1 min-h-0 bg-gray-900 rounded-xl border border-gray-700 p-3 flex flex-col">
            <TaskListPanel tasks={entry.tasks} />
          </div>
          <div className="flex-1 min-h-0 bg-gray-900 rounded-xl border border-gray-700 p-3 flex flex-col">
            <SubAgentListPanel
              agents={children}
              onOpen={(id) => navigate(`/console/${id}`)}
            />
          </div>
        </aside>
      </div>

      {/* Pending tool confirmations */}
      {entry.pendingConfirms.length > 0 && (
        <div className="flex flex-col gap-2">
          {entry.pendingConfirms.map((pc) => (
            <div
              key={pc.call_id}
              className="flex items-center gap-3 bg-orange-950/40 border border-orange-800/60 rounded-lg px-3 py-2"
            >
              <span className="text-orange-300 text-sm shrink-0">⚠ Approve tool</span>
              <code className="flex-1 min-w-0 truncate font-mono text-xs text-orange-200">
                {pc.name}({toOneLine(JSON.stringify(pc.args ?? {}), 120)})
              </code>
              <button
                onClick={() =>
                  sessionId && resolveConfirm(sessionId, pc.call_id, true)
                }
                className="px-3 py-1 rounded-md bg-green-700 hover:bg-green-600 text-white text-xs font-medium shrink-0"
              >
                Allow
              </button>
              <button
                onClick={() =>
                  sessionId && resolveConfirm(sessionId, pc.call_id, false)
                }
                className="px-3 py-1 rounded-md bg-red-800 hover:bg-red-700 text-white text-xs font-medium shrink-0"
              >
                Deny
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="flex gap-2">
        <textarea
          className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 resize-none focus:outline-none focus:border-indigo-500 disabled:opacity-50"
          rows={2}
          placeholder={
            generating
              ? "Agent is generating… wait for it to finish"
              : "Send a message… (Enter to send, Shift+Enter for newline)"
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={generating}
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || generating}
          className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm font-medium transition-colors self-end"
        >
          {generating ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
