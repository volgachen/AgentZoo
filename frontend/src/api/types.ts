export type AgentType = "tool_use" | "claude_code";

export type SessionStatus =
  | "INITIALIZING"
  | "RUNNING"
  | "WAITING_USER"
  | "WAITING_CONFIRM"
  | "COMPLETED"
  | "ERROR";

export type MessageRole = "system" | "user" | "agent" | "tool_call" | "tool";

export type StreamEventType =
  | "text"
  | "assistant_message"
  | "tool_call"
  | "tool_confirm"
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
  // Per-agent config bag. config.tool_approvals is a { toolName: requiresApproval }
  // map overriding each tool's backend default; other keys reserved for future use.
  config: {
    tool_approvals?: Record<string, boolean>;
    [key: string]: unknown;
  };
  openai_model: string;
  openai_base_url: string | null;
  created_at: string;
}

export interface Session {
  id: string;
  agent_id: string;
  title: string | null;
  working_dir: string | null;
  parent_session_id: string | null;
  additional_prompt: string | null;
  additional_prompt_path: string | null;
  status: SessionStatus;
  created_at: string;
  updated_at: string;
  // created_at of the newest message; null for a session with no messages yet.
  last_message_at: string | null;
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

export type TaskStatus = "pending" | "in_progress" | "completed";

// Mirror of backend app/models/domain.py::Task. The id is a per-list monotonic
// integer rendered as a string ("1", "2"); task_list_id is the session id.
export interface Task {
  id: string;
  task_list_id: string;
  subject: string;
  description: string;
  active_form: string | null;
  owner: string | null;
  status: TaskStatus;
  blocks: string[];
  blocked_by: string[];
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
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
