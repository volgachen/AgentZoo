import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AgentTemplate } from "../api/types";
import { useStore } from "../store/sessions";

const AGENT_TYPE_LABEL: Record<string, string> = {
  tool_use: "Tool Use",
  claude_code: "Claude Code",
};

export default function AgentRegistry() {
  const [agents, setAgents] = useState<AgentTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState<string | null>(null);
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [workingDirs, setWorkingDirs] = useState<Record<string, string>>({});
  const launchSession = useStore((s) => s.launchSession);
  const setActive = useStore((s) => s.setActiveSession);
  const navigate = useNavigate();

  useEffect(() => {
    api.agents.list().then((data) => {
      setAgents(data);
      setLoading(false);
    });
  }, []);

  const handleLaunch = async (agentId: string) => {
    setLaunching(agentId);
    try {
      const dir = (workingDirs[agentId] ?? "").trim();
      const sessionId = await launchSession(
        agentId,
        prompts[agentId] ?? "",
        dir || null,
      );
      setActive(sessionId);
      navigate(`/console/${sessionId}`);
    } finally {
      setLaunching(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        Loading agents...
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-white mb-6">Agent Registry</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {agents.map((agent) => (
          <div
            key={agent.id}
            className="bg-gray-800 border border-gray-700 rounded-xl p-5 flex flex-col gap-3"
          >
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-lg font-medium text-white">{agent.name}</h2>
              <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-900 text-indigo-300 whitespace-nowrap">
                {AGENT_TYPE_LABEL[agent.agent_type] ?? agent.agent_type}
              </span>
            </div>
            <p className="text-sm text-gray-400 flex-1">{agent.description}</p>
            <textarea
              className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 resize-none focus:outline-none focus:border-indigo-500"
              rows={2}
              placeholder="Initial prompt (optional)"
              value={prompts[agent.id] ?? ""}
              onChange={(e) =>
                setPrompts((p) => ({ ...p, [agent.id]: e.target.value }))
              }
            />
            <input
              type="text"
              className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500 font-mono"
              placeholder="Working directory (optional, e.g. /home/me/project)"
              value={workingDirs[agent.id] ?? ""}
              onChange={(e) =>
                setWorkingDirs((p) => ({ ...p, [agent.id]: e.target.value }))
              }
            />
            <button
              onClick={() => handleLaunch(agent.id)}
              disabled={launching === agent.id}
              className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium transition-colors"
            >
              {launching === agent.id ? "Launching..." : "Launch"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
