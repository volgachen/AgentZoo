import type { AgentTemplate, Session, Message } from "./types";

// Use the same host the browser connected to, so the app works on any machine in the LAN.
const API_HOST = `${window.location.hostname}:8000`;
const BASE = `http://${API_HOST}/api/v1`;
const WS_BASE = `ws://${API_HOST}/api/v1`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  agents: {
    list: () => request<AgentTemplate[]>("/agents"),
    get: (id: string) => request<AgentTemplate>(`/agents/${id}`),
  },
  sessions: {
    create: (agent_id: string, initial_prompt = "") =>
      request<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({ agent_id, initial_prompt }),
      }),
    get: (id: string) => request<Session>(`/sessions/${id}`),
    messages: (id: string) => request<Message[]>(`/sessions/${id}/messages`),
    delete: (id: string) =>
      request<void>(`/sessions/${id}`, { method: "DELETE" }),
  },
};

export function createSessionSocket(sessionId: string): WebSocket {
  return new WebSocket(`${WS_BASE}/sessions/${sessionId}/stream`);
}
