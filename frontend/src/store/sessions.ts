import { create } from "zustand";
import type { Session, StreamEvent } from "../api/types";
import { api, createSessionSocket } from "../api/client";

interface SessionEntry {
  session: Session;
  events: StreamEvent[];
  socket: WebSocket | null;
}

interface Store {
  sessions: Record<string, SessionEntry>;
  activeSessionId: string | null;

  setActiveSession: (id: string | null) => void;
  launchSession: (
    agentId: string,
    initialPrompt?: string,
    workingDir?: string | null,
    templateDir?: string | null,
  ) => Promise<string>;
  sendMessage: (sessionId: string, content: string) => void;
  closeSession: (sessionId: string) => Promise<void>;
  refreshSession: (sessionId: string) => Promise<void>;
}

export const useStore = create<Store>((set, get) => ({
  sessions: {},
  activeSessionId: null,

  setActiveSession: (id) => set({ activeSessionId: id }),

  launchSession: async (agentId, initialPrompt = "", workingDir = null, templateDir = null) => {
    const session = await api.sessions.create(agentId, initialPrompt, workingDir, templateDir);
    const socket = createSessionSocket(session.id);

    const seedEvents: StreamEvent[] = initialPrompt
      ? [{ type: "user", data: initialPrompt }]
      : [];

    set((s) => ({
      sessions: {
        ...s.sessions,
        [session.id]: { session, events: seedEvents, socket },
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
        return {
          sessions: {
            ...s.sessions,
            [session.id]: { ...entry, events: [...entry.events, frame as StreamEvent] },
          },
        };
      });
    };

    socket.onclose = () => {
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
      const userEvent: StreamEvent = { type: "user", data: content };
      return {
        sessions: {
          ...s.sessions,
          [sessionId]: { ...cur, events: [...cur.events, userEvent] },
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
