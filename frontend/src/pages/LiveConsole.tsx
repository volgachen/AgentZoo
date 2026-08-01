import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useStore } from "../store/sessions";
import type { StreamEvent } from "../api/types";
import TaskListPanel from "../components/TaskListPanel";
import SubAgentListPanel from "../components/SubAgentListPanel";
import ToolConfirmPanel from "../components/ToolConfirmPanel";
import ToolPreview from "../components/ToolPreview";

const EVENT_STYLE: Record<string, string> = {
  text: "text-gray-200",
  tool_call: "text-yellow-400",
  tool_confirm: "text-orange-400",
  tool_result: "text-amber-300",
  status: "text-blue-400",
  error: "text-red-400",
  done: "text-green-500",
  session_state: "text-gray-500",
  assistant_message: "text-gray-200",
  user: "text-indigo-300",
};

interface AssistantToolCall {
  id?: string;
  type?: string;
  function?: {
    name?: string;
    arguments?: string;
  };
}

interface AssistantPayload {
  role?: string;
  content?: string | null;
  tool_calls?: AssistantToolCall[] | null;
}

interface ToolCallView {
  kind: "tool_call";
  callId: string;
  name: string;
  args: unknown;
  result?: unknown;
}

type ConsoleItem = StreamEvent | ToolCallView;

function parseAssistantData(raw: string): AssistantPayload {
  try {
    const obj = JSON.parse(raw);
    if (obj && typeof obj === "object" && obj.role === "assistant") {
      return obj as AssistantPayload;
    }
  } catch {
    // Legacy rows stored plain assistant text.
  }
  return { role: "assistant", content: raw, tool_calls: null };
}

function parseToolArguments(raw: string | undefined): unknown {
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function parseJsonObject(raw: string): Record<string, unknown> | null {
  try {
    const obj = JSON.parse(raw);
    return obj && typeof obj === "object" ? (obj as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function resultToText(result: unknown): string {
  if (typeof result === "string") return result;
  if (result === undefined) return "";
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

function toOneLine(s: string, max = 200): string {
  const flat = s.replace(/\s+/g, " ").trim();
  return flat.length > max ? flat.slice(0, max) + "…" : flat;
}

function buildConsoleItems(events: StreamEvent[]): ConsoleItem[] {
  const items: ConsoleItem[] = [];
  const toolCallsById = new Map<string, ToolCallView>();
  const attachResult = (callId: string | undefined, name: string | undefined, result: unknown): boolean => {
    if (callId && toolCallsById.has(callId)) {
      toolCallsById.get(callId)!.result = result;
      return true;
    }

    const reversedCalls = [...items]
      .filter((item): item is ToolCallView => "kind" in item && item.kind === "tool_call")
      .reverse();
    const fallback = reversedCalls.find(
      (item) => item.result === undefined && (!name || item.name === name),
    );
    if (fallback) {
      fallback.result = result;
      return true;
    }

    return false;
  };

  for (const event of events) {
    if (event.type === "assistant_message") {
      const payload = parseAssistantData(event.data);
      const content = payload.content ?? "";
      if (content) {
        items.push({ type: "assistant_message", data: content });
      }
      for (const [index, toolCall] of (payload.tool_calls ?? []).entries()) {
        const name = toolCall.function?.name ?? "unknown";
        const callId = toolCall.id ?? `${items.length}:tool:${index}`;
        const item: ToolCallView = {
          kind: "tool_call",
          callId,
          name,
          args: parseToolArguments(toolCall.function?.arguments),
        };
        items.push(item);
        toolCallsById.set(callId, item);
      }
      continue;
    }

    if (event.type === "tool_call" || event.type === "tool_confirm") {
      const obj = parseJsonObject(event.data);
      const name = typeof obj?.name === "string" ? obj.name : "tool";
      const callId =
        typeof obj?.call_id === "string"
          ? obj.call_id
          : typeof obj?.id === "string"
            ? obj.id
            : `${items.length}:tool`;
      const existing = toolCallsById.get(callId);
      if (existing) {
        existing.name = name;
        existing.args = obj?.args ?? existing.args;
      } else {
        const item: ToolCallView = {
          kind: "tool_call",
          callId,
          name,
          args: obj?.args ?? {},
        };
        items.push(item);
        toolCallsById.set(callId, item);
      }
      continue;
    }

    if (event.type === "tool_result") {
      const obj = parseJsonObject(event.data);
      const attached = attachResult(
        typeof obj?.call_id === "string" ? obj.call_id : undefined,
        typeof obj?.name === "string" ? obj.name : undefined,
        obj?.result ?? obj?.content ?? event.data,
      );
      if (!attached) {
        items.push(event);
      }
      continue;
    }

    items.push(event);
  }

  return items;
}

function ToolCallLine({ item }: { item: ToolCallView }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="text-left font-mono text-sm text-yellow-400">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left flex items-start gap-1 hover:bg-gray-800/40 rounded px-1 -mx-1 cursor-pointer"
        title={expanded ? "Collapse" : "Expand"}
      >
        <span className="text-gray-500 select-none">{expanded ? "▾" : "▸"}</span>
        <span className="shrink-0">⚙ {item.name}</span>
        <span className="text-gray-500 truncate">{item.callId}</span>
      </button>
      {expanded && (
        <div className="ml-4">
          <ToolPreview name={item.name} args={item.args} className="mt-1" />
        </div>
      )}
      {item.result !== undefined && (
        <pre className="mt-1 ml-4 px-2 py-1.5 bg-gray-950/60 border border-gray-800 rounded whitespace-pre-wrap break-all text-xs text-amber-200 overflow-auto max-h-72">
          {resultToText(item.result)}
        </pre>
      )}
    </div>
  );
}

function EventLine({ event }: { event: StreamEvent }) {
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
      {event.type === "tool_result" ? toOneLine(body) : body}
    </div>
  );
}

function isToolCallView(item: ConsoleItem): item is ToolCallView {
  return "kind" in item && item.kind === "tool_call";
}

function ConsoleItemLine({ item }: { item: ConsoleItem }) {
  if (isToolCallView(item)) {
    return <ToolCallLine item={item} />;
  }
  return <EventLine event={item} />;
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
  }, [entry?.events.length, entry?.session.status]);

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
  const generating = session.status === "RUNNING";
  const consoleItems = buildConsoleItems(events);

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
    <div className="relative flex flex-col h-full p-4 gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-white">
          {session.title ?? "Live Console"}
        </h1>
        <div className="text-left">
          <p className="text-xs text-gray-500 font-mono">{session.id}</p>
          <p className="text-xs text-gray-500 font-mono">
            <span className="text-gray-600">cwd: </span>
            {session.working_dir ?? "—"}
          </p>
        </div>
        <div className="flex items-center gap-2">
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
          {consoleItems.length === 0 && (
            <p className="text-gray-600 text-sm font-mono">Waiting for output…</p>
          )}
          {consoleItems.map((item, i) => (
            <ConsoleItemLine key={i} item={item} />
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
        <div className="pointer-events-none absolute inset-x-4 bottom-24 z-30 flex flex-col items-stretch gap-2 lg:right-[21.75rem]">
          {entry.pendingConfirms.map((pc) => (
            <ToolConfirmPanel
              key={pc.call_id}
              name={pc.name}
              args={pc.args}
              callId={pc.call_id}
              onApprove={(message) =>
                sessionId && resolveConfirm(sessionId, pc.call_id, true, message)
              }
              onDeny={(message) =>
                sessionId && resolveConfirm(sessionId, pc.call_id, false, message)
              }
            />
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
