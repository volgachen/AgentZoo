import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useStore } from "../store/sessions";
import type { StreamEvent } from "../api/types";

const EVENT_STYLE: Record<string, string> = {
  text: "text-gray-200",
  tool_call: "text-yellow-400",
  tool_result: "text-amber-300",
  status: "text-blue-400",
  error: "text-red-400",
  done: "text-green-500",
  session_state: "text-gray-500",
  agent_message: "text-gray-200",
  user: "text-indigo-300",
};

// tool_call data is {name,args}; tool_result data is {name,result}. Render them
// readably instead of dumping raw JSON.
function formatToolData(type: string, raw: string): string {
  try {
    const obj = JSON.parse(raw);
    if (type === "tool_call") {
      return `${obj.name}(${JSON.stringify(obj.args ?? {})})`;
    }
    if (type === "tool_result") {
      return `${obj.name} → ${typeof obj.result === "string" ? obj.result : JSON.stringify(obj.result)}`;
    }
  } catch {
    // fall through to raw
  }
  return raw;
}

function EventLine({ event }: { event: StreamEvent }) {
  const style = EVENT_STYLE[event.type] ?? "text-gray-300";
  const prefix =
    event.type === "tool_call"
      ? "⚙ "
      : event.type === "tool_result"
        ? "↩ "
        : event.type === "status"
          ? "● "
          : event.type === "error"
            ? "✗ "
            : event.type === "done"
              ? "✓ "
              : event.type === "user"
                ? "❯ "
                : "";
  const body =
    event.type === "tool_call" || event.type === "tool_result"
      ? formatToolData(event.type, event.data)
      : typeof event.data === "string"
        ? event.data
        : JSON.stringify(event.data);
  return (
    <div className={`font-mono text-sm whitespace-pre-wrap break-all ${style}`}>
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
  const openSession = useStore((s) => s.openSession);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const entry = sessionId ? sessions[sessionId] : undefined;

  // Backfill history + attach a live socket when viewing a session we didn't
  // launch in this tab (e.g. subagent-spawned). No-op if already live.
  useEffect(() => {
    if (sessionId) openSession(sessionId);
  }, [sessionId, openSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entry?.events.length]);

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
                  : session.status === "WAITING_USER"
                    ? "bg-blue-900 text-blue-300"
                    : "bg-gray-700 text-gray-400"
            }`}
          >
            {session.status}
          </span>
        </div>
      </div>

      {/* Event log */}
      <div className="flex-1 bg-gray-900 rounded-xl border border-gray-700 p-4 overflow-y-auto flex flex-col gap-1 min-h-0">
        {events.length === 0 && (
          <p className="text-gray-600 text-sm font-mono">Waiting for output…</p>
        )}
        {events.map((ev, i) => (
          <EventLine key={i} event={ev} />
        ))}
        <div ref={bottomRef} />
      </div>

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
