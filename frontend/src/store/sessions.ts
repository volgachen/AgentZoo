import { create } from "zustand";
import type { Session, StreamEvent } from "../api/types";
import { api, createSessionSocket } from "../api/client";

interface SessionEntry {
  session: Session;
  events: StreamEvent[];
  socket: WebSocket | null;
  generating: boolean;
}

interface Store {
  sessions: Record<string, SessionEntry>;
  activeSessionId: string | null;

  setActiveSession: (id: string | null) => void;
  hydrateSessions: () => Promise<void>;
  launchSession: (
    agentId: string,
    workingDir?: string | null,
    templateDir?: string | null,
    env?: string | null,
  ) => Promise<string>;
  sendMessage: (sessionId: string, content: string) => void;
  closeSession: (sessionId: string) => Promise<void>;
  refreshSession: (sessionId: string) => Promise<void>;
}

export const useStore = create<Store>((set, get) => ({
  sessions: {},
  activeSessionId: null,

  setActiveSession: (id) => set({ activeSessionId: id }),

  // Pull every session the gateway knows about and merge any we don't already
  // track into the store as display-only entries (no live socket). Sessions we
  // launched in this tab keep their socket/events untouched; we only refresh
  // their session metadata. Lets the dashboard show the full derivation tree
  // even across a page reload.
  hydrateSessions: async () => {
    const remote = await api.sessions.list();
    set((s) => {
      const next = { ...s.sessions };
      for (const session of remote) {
        const existing = next[session.id];
        next[session.id] = existing
          ? { ...existing, session }
          : { session, events: [], socket: null, generating: false };
      }
      return { sessions: next };
    });
  },

  launchSession: async (agentId, workingDir = null, templateDir = null, env = null) => {
    const session = await api.sessions.create(agentId, workingDir, templateDir, env);
    const socket = createSessionSocket(session.id);

    set((s) => ({
      sessions: {
        ...s.sessions,
        [session.id]: {
          session,
          events: [],
          socket,
          generating: false,
        },
      },
    }));

    socket.onmessage = (e) => {
      const frame = JSON.parse(e.data);
      set((s) => {
        const entry = s.sessions[session.id];
        if (!entry) return s;
        if (frame.type === "session_state") {
          return {
            sessions: {
              ...s.sessions,
              [session.id]: { ...entry, session: frame.data as Session },
            },
          };
        }
        const isTerminal = frame.type === "done" || frame.type === "error";
        const isUser = frame.type === "user";
        return {
          sessions: {
            ...s.sessions,
            [session.id]: {
              ...entry,
              events: [...entry.events, frame as StreamEvent],
              generating: isTerminal
                ? false
                : isUser
                  ? true
                  : entry.generating,
            },
          },
        };
      });
    };

    socket.onclose = () => {
      set((s) => {
        const entry = s.sessions[session.id];
        if (!entry) return s;
        return {
          sessions: {
            ...s.sessions,
            [session.id]: { ...entry, generating: false },
          },
        };
      });
      // Refresh session status from server on disconnect
      get().refreshSession(session.id);
    };

    return session.id;
  },

  sendMessage: (sessionId, content) => {
    const entry = get().sessions[sessionId];
    if (!entry?.socket) return;
    entry.socket.send(JSON.stringify({ content }));
    set((s) => {
      const cur = s.sessions[sessionId];
      if (!cur) return s;
      return {
        sessions: {
          ...s.sessions,
          [sessionId]: {
            ...cur,
            generating: true,
          },
        },
      };
    });
  },

  closeSession: async (sessionId) => {
    const entry = get().sessions[sessionId];
    entry?.socket?.close();
    await api.sessions.delete(sessionId);
    set((s) => {
      const next = { ...s.sessions };
      delete next[sessionId];
      return {
        sessions: next,
        activeSessionId: s.activeSessionId === sessionId ? null : s.activeSessionId,
      };
    });
  },

  refreshSession: async (sessionId) => {
    const session = await api.sessions.get(sessionId);
    set((s) => {
      const entry = s.sessions[sessionId];
      if (!entry) return s;
      return {
        sessions: { ...s.sessions, [sessionId]: { ...entry, session } },
      };
    });
  },
}));
