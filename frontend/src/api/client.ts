import type {
  AgentTemplate,
  Session,
  Message,
  Plugin,
  PluginLogLine,
} from "./types";

// Use the same host the browser connected to, so the app works on any machine in the LAN.
const API_HOST = `${window.location.hostname}:12598`;
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

export interface DirEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

export interface BrowseResponse {
  path: string;
  parent: string | null;
  entries: DirEntry[];
}

function browseQuery(path: string | null | undefined): string {
  return path ? `?path=${encodeURIComponent(path)}` : "";
}

export const api = {
  agents: {
    list: () => request<AgentTemplate[]>("/agents"),
    get: (id: string) => request<AgentTemplate>(`/agents/${id}`),
  },
  sessions: {
    create: (
      agent_id: string,
      working_dir: string | null = null,
      template_dir: string | null = null,
    ) =>
      request<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({ agent_id, working_dir, template_dir }),
      }),
    get: (id: string) => request<Session>(`/sessions/${id}`),
    messages: (id: string) => request<Message[]>(`/sessions/${id}/messages`),
    delete: (id: string) =>
      request<void>(`/sessions/${id}`, { method: "DELETE" }),
  },
  fs: {
    browse: (path?: string | null) =>
      request<BrowseResponse>(`/fs/browse${browseQuery(path)}`),
    templates: (path?: string | null) =>
      request<BrowseResponse>(`/fs/templates${browseQuery(path)}`),
    home: () => request<{ home: string; templates_root: string }>("/fs/home"),
  },
  plugins: {
    list: () => request<Plugin[]>("/plugins"),
    get: (id: string) => request<Plugin>(`/plugins/${id}`),
    create: (name: string, code: string) =>
      request<Plugin>("/plugins", {
        method: "POST",
        body: JSON.stringify({ name, code }),
      }),
    update: (id: string, body: { name?: string; code?: string }) =>
      request<Plugin>(`/plugins/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    delete: (id: string) =>
      request<void>(`/plugins/${id}`, { method: "DELETE" }),
    start: (id: string) =>
      request<Plugin>(`/plugins/${id}/start`, { method: "POST" }),
    stop: (id: string) =>
      request<Plugin>(`/plugins/${id}/stop`, { method: "POST" }),
    restart: (id: string) =>
      request<Plugin>(`/plugins/${id}/restart`, { method: "POST" }),
    logs: (id: string) =>
      request<{ lines: PluginLogLine[] }>(`/plugins/${id}/logs`),
    clearLogs: (id: string) =>
      request<void>(`/plugins/${id}/logs/clear`, { method: "POST" }),
  },
};

export function createSessionSocket(sessionId: string): WebSocket {
  return new WebSocket(`${WS_BASE}/sessions/${sessionId}/stream`);
}

export function createPluginSocket(pluginId: string): WebSocket {
  return new WebSocket(`${WS_BASE}/plugins/${pluginId}/stream`);
}
