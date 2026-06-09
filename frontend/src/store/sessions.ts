import { create } from "zustand";
import type { Message, Session, StreamEvent } from "../api/types";
import { api, createSessionSocket } from "../api/client";

interface SessionEntry {
  session: Session;
  events: StreamEvent[];
  socket: WebSocket | null;
  generating: boolean;
}

// Map a persisted Message into the StreamEvent shape the console renders, so
// REST-loaded history and live WS events share one render path.
function messageToEvent(m: Message): StreamEvent {
  switch (m.role) {
    case "user":
      return { type: "user", data: m.content };
    case "tool":
      return { type: "tool_call", data: m.content };
    case "system":
      return { type: "status", data: m.content };
    case "agent":
    default:
      return { type: "text", data: m.content };
  }
}

interface Store {
  sessions: Record<string, SessionEntry>;
  activeSessionId: string | null;

  setActiveSession: (id: string | null) => void;
  hydrateSessions: () => Promise<void>;
  openSession: (sessionId: string) => Promise<void>;
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

export const useStore = create<Store>((set, get) => {
  // Open a WS for a session and wire its frames into the store. Shared by
  // launchSession (sessions we start here) and openSession (sessions started
  // elsewhere — e.g. spawned by a subagent — that we're now viewing).
  const attachSocket = (sessionId: string): WebSocket => {
    const socket = createSessionSocket(sessionId);

    socket.onmessage = (e) => {
      const frame = JSON.parse(e.data);
      set((s) => {
        const entry = s.sessions[sessionId];
        if (!entry) return s;
        if (frame.type === "session_state") {
          return {
            sessions: {
              ...s.sessions,
              [sessionId]: { ...entry, session: frame.data as Session },
            },
          };
        }
        const isTerminal = frame.type === "done" || frame.type === "error";
        const isUser = frame.type === "user";
        return {
          sessions: {
            ...s.sessions,
            [sessionId]: {
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
        const entry = s.sessions[sessionId];
        if (!entry) return s;
        return {
          sessions: {
            ...s.sessions,
            [sessionId]: { ...entry, generating: false },
          },
        };
      });
      // Refresh session status from server on disconnect
      get().refreshSession(sessionId);
    };

    return socket;
  };

  return {
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

    // Open a session for viewing: backfill its message history from REST, and
    // attach a live WS if one isn't already connected. Used when navigating to
    // a session we didn't launch in this tab (subagent-spawned, another tab,
    // post-reload) — those arrive via hydrateSessions with events:[] socket:null
    // and would otherwise render an empty console.
    openSession: async (sessionId) => {
      const existing = get().sessions[sessionId];
      // Already live in this tab (launched here / mid-stream / opened a moment
      // ago): don't clobber the in-memory buffer or open a second socket. The
      // socket is written synchronously below before any await, so React
      // StrictMode's double-invoke (and rapid re-navigation) hits this guard on
      // the second call instead of racing to create a duplicate stream.
      if (existing?.socket) {
        set({ activeSessionId: sessionId });
        return;
      }

      // Synchronously claim the slot: attach the socket and store it before the
      // first await. zustand's set is synchronous, so a concurrent call now sees
      // socket != null above and bails out.
      const socket = attachSocket(sessionId);
      set((s) => {
        const entry = s.sessions[sessionId];
        return {
          activeSessionId: sessionId,
          sessions: {
            ...s.sessions,
            [sessionId]: entry
              ? { ...entry, socket }
              // Placeholder until we fetch the record below; status is provisional.
              : {
                  session: {
                    id: sessionId,
                    agent_id: "",
                    working_dir: null,
                    parent_session_id: null,
                    status: "RUNNING",
                    created_at: "",
                    updated_at: "",
                  },
                  events: [],
                  socket,
                  generating: false,
                },
          },
        };
      });

      // Backfill: fetch the session record (if we lacked it) and history, then
      // merge in without disturbing the socket or any live events the WS may
      // have already appended.
      const needsSession = !existing?.session;
      const [fetchedSession, messages] = await Promise.all([
        needsSession ? api.sessions.get(sessionId) : Promise.resolve(null),
        api.sessions.messages(sessionId),
      ]);
      const history = messages.map(messageToEvent);

      set((s) => {
        const entry = s.sessions[sessionId];
        if (!entry) return s;
        return {
          sessions: {
            ...s.sessions,
            [sessionId]: {
              ...entry,
              session: fetchedSession ?? entry.session,
              // History first, then any events the live socket already delivered.
              events: [...history, ...entry.events],
            },
          },
        };
      });
    },

    launchSession: async (agentId, workingDir = null, templateDir = null, env = null) => {
      const session = await api.sessions.create(agentId, workingDir, templateDir, env);
      const socket = attachSocket(session.id);

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
  };
});
