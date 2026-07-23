import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store/sessions";
import type { SessionStatus } from "../api/types";

const STATUS_STYLE: Record<SessionStatus, string> = {
  INITIALIZING: "bg-yellow-900 text-yellow-300",
  RUNNING: "bg-green-900 text-green-300",
  WAITING_USER: "bg-blue-900 text-blue-300",
  WAITING_CONFIRM: "bg-orange-900 text-orange-300",
  COMPLETED: "bg-gray-700 text-gray-400",
  ERROR: "bg-red-900 text-red-300",
};

// A session is "active" when it holds a live WebSocket to the backend stream.
function isSocketLive(socket: WebSocket | null): boolean {
  return (
    socket != null &&
    (socket.readyState === WebSocket.OPEN ||
      socket.readyState === WebSocket.CONNECTING)
  );
}

// Hoverable menu listing every session with a live socket, so a worker can jump
// between concurrent sessions without going back to the dashboard.
export default function ActiveSessionsMenu({
  currentSessionId,
}: {
  currentSessionId?: string;
}) {
  const sessions = useStore((s) => s.sessions);
  const setActive = useStore((s) => s.setActiveSession);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const active = Object.values(sessions)
    .filter((e) => isSocketLive(e.socket))
    .map((e) => e.session)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  const jump = (id: string) => {
    setOpen(false);
    setActive(id);
    navigate(`/console/${id}`);
  };

  return (
    <div
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-xs font-medium text-gray-300 border border-gray-700"
      >
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400" />
        Active sessions
        <span className="text-gray-500">{active.length}</span>
        <span className="text-gray-500 text-[10px]">▾</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full pt-1 w-72 z-20">
          <div className="rounded-lg border border-gray-700 bg-gray-900 shadow-xl py-1">
          {active.length === 0 ? (
            <p className="px-3 py-2 text-xs text-gray-500">No active sessions.</p>
          ) : (
            active.map((s) => {
              const isCurrent = s.id === currentSessionId;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => jump(s.id)}
                  className={`w-full flex items-center justify-between gap-2 px-3 py-1.5 text-left hover:bg-gray-800 ${
                    isCurrent ? "bg-gray-800/60" : ""
                  }`}
                >
                  <span className="text-xs text-gray-300 truncate">
                    {s.title ?? `${s.id.slice(0, 8)}…`}
                    {isCurrent && (
                      <span className="ml-1 text-[10px] text-indigo-400">
                        current
                      </span>
                    )}
                  </span>
                  <span
                    className={`shrink-0 px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_STYLE[s.status]}`}
                  >
                    {s.status}
                  </span>
                </button>
              );
            })
          )}
          </div>
        </div>
      )}
    </div>
  );
}
