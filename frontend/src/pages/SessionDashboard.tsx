import { useNavigate } from "react-router-dom";
import { useStore } from "../store/sessions";
import type { SessionStatus } from "../api/types";

const STATUS_STYLE: Record<SessionStatus, string> = {
  INITIALIZING: "bg-yellow-900 text-yellow-300",
  RUNNING: "bg-green-900 text-green-300",
  WAITING_USER: "bg-blue-900 text-blue-300",
  COMPLETED: "bg-gray-700 text-gray-400",
  ERROR: "bg-red-900 text-red-300",
};

export default function SessionDashboard() {
  const sessions = useStore((s) => s.sessions);
  const setActive = useStore((s) => s.setActiveSession);
  const closeSession = useStore((s) => s.closeSession);
  const navigate = useNavigate();

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
              <th className="pb-3 pr-4 font-medium">Events</th>
              <th className="pb-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(({ session, events }) => (
              <tr
                key={session.id}
                className="border-b border-gray-800 hover:bg-gray-800/50 transition-colors"
              >
                <td className="py-3 pr-4 font-mono text-gray-300 text-xs">
                  {session.id.slice(0, 8)}…
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
