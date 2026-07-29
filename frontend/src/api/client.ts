import type {
  AgentTemplate,
  AgentType,
  Session,
  Message,
  PluginDefinition,
  PluginInstance,
  PluginLogLine,
  PluginRun,
  Task,
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
  if (res.status === 204) return undefined as T;
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

function limitQuery(limit?: number): string {
  return limit == null ? "" : `?limit=${encodeURIComponent(String(limit))}`;
}

export interface CreateAgentPayload {
  name: string;
  description: string;
  agent_type: AgentType;
  system_prompt: string;
  tool_names: string[];
  openai_model: string;
  openai_base_url: string | null;
}

export type UpdateAgentPayload = Partial<Omit<CreateAgentPayload, "agent_type">>;

export interface CreatePluginInstancePayload {
  plugin_id: string;
  display_name: string;
  config?: Record<string, unknown> | null;
  auto_start?: boolean;
}

export interface UpdatePluginInstancePayload {
  display_name?: string;
  config?: Record<string, unknown> | null;
  auto_start?: boolean;
}

export const api = {
  agents: {
    list: () => request<AgentTemplate[]>("/agents"),
    get: (id: string) => request<AgentTemplate>(`/agents/${id}`),
    create: (body: CreateAgentPayload) =>
      request<AgentTemplate>("/agents", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: string, body: UpdateAgentPayload) =>
      request<AgentTemplate>(`/agents/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    delete: (id: string) =>
      request<void>(`/agents/${id}`, { method: "DELETE" }),
  },
  tools: {
    list: () => request<string[]>("/tools"),
  },
  sessions: {
    create: (
      agent_id: string,
      working_dir: string | null = null,
      template_dir: string | null = null,
      additional_prompt: string | null = null,
      additional_prompt_path: string | null = null,
      title: string | null = null,
    ) =>
      request<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({ agent_id, working_dir, template_dir, additional_prompt, additional_prompt_path, title }),
      }),
    updateTitle: (id: string, title: string) =>
      request<Session>(`/sessions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      }),
    get: (id: string) => request<Session>(`/sessions/${id}`),
    list: () => request<Session[]>("/sessions"),
    messages: (id: string) => request<Message[]>(`/sessions/${id}/messages`),
    tasks: (id: string) => request<Task[]>(`/sessions/${id}/tasks`),
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
    catalog: () => request<PluginDefinition[]>("/plugins/catalog"),
    definition: (id: string) => request<PluginDefinition>(`/plugins/catalog/${id}`),
    instances: () => request<PluginInstance[]>("/plugins/instances"),
    instance: (id: string) => request<PluginInstance>(`/plugins/instances/${id}`),
    createInstance: (body: CreatePluginInstancePayload) =>
      request<PluginInstance>("/plugins/instances", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    updateInstance: (id: string, body: UpdatePluginInstancePayload) =>
      request<PluginInstance>(`/plugins/instances/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    deleteInstance: (id: string) =>
      request<void>(`/plugins/instances/${id}`, { method: "DELETE" }),
    startInstance: (id: string) =>
      request<PluginRun>(`/plugins/instances/${id}/start`, { method: "POST" }),
    stopInstance: (id: string) =>
      request<PluginInstance>(`/plugins/instances/${id}/stop`, { method: "POST" }),
    restartInstance: (id: string) =>
      request<PluginRun>(`/plugins/instances/${id}/restart`, { method: "POST" }),
    runs: (instanceId: string) =>
      request<PluginRun[]>(`/plugins/instances/${instanceId}/runs`),
    run: (runId: string) => request<PluginRun>(`/plugins/runs/${runId}`),
    runLogs: (runId: string, limit?: number) =>
      request<PluginLogLine[]>(`/plugins/runs/${runId}/logs${limitQuery(limit)}`),
    instanceLogs: (instanceId: string, limit?: number) =>
      request<PluginLogLine[]>(`/plugins/instances/${instanceId}/logs${limitQuery(limit)}`),
  },
};

export function createSessionSocket(sessionId: string): WebSocket {
  return new WebSocket(`${WS_BASE}/sessions/${sessionId}/stream`);
}

export function createPluginSocket(instanceId: string): WebSocket {
  return new WebSocket(`${WS_BASE}/plugins/instances/${instanceId}/stream`);
}
