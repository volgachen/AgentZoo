export type AgentType = "tool_use" | "claude_code";

export type SessionStatus =
  | "INITIALIZING"
  | "RUNNING"
  | "WAITING_USER"
  | "COMPLETED"
  | "ERROR";

export type MessageRole = "system" | "user" | "agent" | "tool_call" | "tool";

export type StreamEventType =
  | "text"
  | "tool_call"
  | "tool_result"
  | "status"
  | "error"
  | "done"
  | "user";

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  agent_type: AgentType;
  system_prompt: string;
  tool_names: string[];
  openai_model: string;
  openai_base_url: string | null;
  created_at: string;
}

export interface Session {
  id: string;
  agent_id: string;
  working_dir: string | null;
  parent_session_id: string | null;
  status: SessionStatus;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: MessageRole;
  content: string;
  created_at: string;
}

export interface StreamEvent {
  type: StreamEventType;
  data: string;
}

export type PluginStatus = "stopped" | "running" | "exited" | "errored";

export interface Plugin {
  id: string;
  name: string;
  code: string;
  status: PluginStatus;
  last_started_at: string | null;
  last_exited_at: string | null;
  last_exit_code: number | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export type PluginLogStream = "stdout" | "stderr" | "system";

export interface PluginLogLine {
  ts: string;
  stream: PluginLogStream;
  line: string;
}

export type PluginWsFrame =
  | { type: "plugin_state"; data: Plugin }
  | { type: "log"; data: PluginLogLine }
  | { type: "status"; data: { status: PluginStatus; error?: string | null } }
  | { type: "logs_cleared"; data: null }
  | { type: "error"; data: string };
