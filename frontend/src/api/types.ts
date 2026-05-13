export type AgentType = "tool_use" | "claude_code";

export type SessionStatus =
  | "INITIALIZING"
  | "RUNNING"
  | "WAITING_USER"
  | "COMPLETED"
  | "ERROR";

export type MessageRole = "system" | "user" | "agent" | "tool";

export type StreamEventType =
  | "text"
  | "tool_call"
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
  created_at: string;
}

export interface Session {
  id: string;
  agent_id: string;
  working_dir: string | null;
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
