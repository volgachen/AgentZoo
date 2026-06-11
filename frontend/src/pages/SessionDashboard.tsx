import { useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { useStore } from "../store/sessions";
import type { Session, SessionStatus, StreamEvent } from "../api/types";

function formatCreatedAt(iso: string): string {
  // The backend stores created_at as UTC but the DATETIME column serializes
  // without a timezone suffix, so a bare "2026-06-09T03:00:00" would be parsed
  // as local time. Append "Z" when no offset is present so it's read as UTC.
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

const STATUS_STYLE: Record<SessionStatus, string> = {
  INITIALIZING: "bg-yellow-900 text-yellow-300",
  RUNNING: "bg-green-900 text-green-300",
  WAITING_USER: "bg-blue-900 text-blue-300",
  COMPLETED: "bg-gray-700 text-gray-400",
  ERROR: "bg-red-900 text-red-300",
};

interface Entry {
  session: Session;
  events: StreamEvent[];
}

interface Row {
  entry: Entry;
  depth: number;
  // Set when this session has a parent that isn't currently loaded in the
  // store; it's rendered as a root but we still hint at the missing parent.
  orphanParent: string | null;
}

// Flatten the sessions into a depth-first list ordered as a parent -> child
// forest. Children whose parent is not loaded (closed, or owned by another
// client) become roots so nothing is ever hidden.
function buildForest(entries: Entry[]): Row[] {
  const byId = new Map(entries.map((e) => [e.session.id, e]));
  const childrenOf = new Map<string, Entry[]>();
  for (const e of entries) {
    const pid = e.session.parent_session_id;
    if (pid && byId.has(pid)) {
      const arr = childrenOf.get(pid) ?? [];
      arr.push(e);
      childrenOf.set(pid, arr);
    }
  }

  const byCreated = (a: Entry, b: Entry) =>
    a.session.created_at.localeCompare(b.session.created_at);

  const roots = entries
    .filter((e) => {
      const pid = e.session.parent_session_id;
      return !pid || !byId.has(pid);
    })
    .sort(byCreated);

  const rows: Row[] = [];
  const visited = new Set<string>();
  const walk = (entry: Entry, depth: number) => {
    if (visited.has(entry.session.id)) return; // guard against cycles
    visited.add(entry.session.id);
    const pid = entry.session.parent_session_id;
    rows.push({
      entry,
      depth,
      orphanParent: pid && !byId.has(pid) ? pid : null,
    });
    const kids = (childrenOf.get(entry.session.id) ?? []).slice().sort(byCreated);
    for (const kid of kids) walk(kid, depth + 1);
  };
  for (const root of roots) walk(root, 0);
  return rows;
}

export default function SessionDashboard() {
  const sessions = useStore((s) => s.sessions);
  const setActive = useStore((s) => s.setActiveSession);
  const closeSession = useStore((s) => s.closeSession);
  const hydrateSessions = useStore((s) => s.hydrateSessions);
  const navigate = useNavigate();

  useEffect(() => {
    hydrateSessions().catch((err) =>
      console.error("failed to hydrate sessions", err),
    );
  }, [hydrateSessions]);

  const entries = Object.values(sessions);

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-gray-400">
        <p>No active sessions.</p>
        <button
          onClick={() => navigate("/")}
          className="text-indigo-400 hover:text-indigo-300 text-sm underline"
        >
          Launch one from the Agent Registry
        </button>
      </div>
    );
  }

  const rows = buildForest(entries);

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-white mb-6">Sessions</h1>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              <th className="pb-3 pr-4 font-medium">Session ID</th>
              <th className="pb-3 pr-4 font-medium">Agent</th>
              <th className="pb-3 pr-4 font-medium">Working Dir</th>
              <th className="pb-3 pr-4 font-medium">Status</th>
              <th className="pb-3 pr-4 font-medium">Created</th>
              <th className="pb-3 pr-4 font-medium">Events</th>
              <th className="pb-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ entry: { session, events }, depth, orphanParent }) => (
              <tr
                key={session.id}
                className="border-b border-gray-800 hover:bg-gray-800/50 transition-colors"
              >
                <td className="py-3 pr-4 font-mono text-gray-300 text-xs">
                  <span
                    className="inline-flex items-center gap-1"
                    style={{ paddingLeft: `${depth * 1.25}rem` }}
                  >
                    {depth > 0 && <span className="text-gray-600">└─</span>}
                    <span>{session.id.slice(0, 8)}…</span>
                    {orphanParent && (
                      <span className="ml-1 text-[10px] text-gray-600">
                        ↳ from {orphanParent.slice(0, 8)}…
                      </span>
                    )}
                  </span>
                </td>
                <td className="py-3 pr-4 text-gray-300">{session.agent_id}</td>
                <td className="py-3 pr-4 font-mono text-gray-400 text-xs">
                  {session.working_dir ?? <span className="text-gray-600">—</span>}
                </td>
                <td className="py-3 pr-4">
                  <span
                    className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLE[session.status]}`}
                  >
                    {session.status}
                  </span>
                </td>
                <td className="py-3 pr-4 text-gray-400 text-xs whitespace-nowrap">
                  {formatCreatedAt(session.created_at)}
                </td>
                <td className="py-3 pr-4 text-gray-400">{events.length}</td>
                <td className="py-3 flex gap-2">
                  <button
                    onClick={() => {
                      setActive(session.id);
                      navigate(`/console/${session.id}`);
                    }}
                    className="px-3 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white text-xs transition-colors"
                  >
                    Open
                  </button>
                  <button
                    onClick={() => closeSession(session.id)}
                    className="px-3 py-1 rounded bg-gray-700 hover:bg-red-800 text-gray-300 hover:text-white text-xs transition-colors"
                  >
                    Close
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
