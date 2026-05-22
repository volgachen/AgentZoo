import { create } from "zustand";
import type { Plugin, PluginLogLine, PluginWsFrame } from "../api/types";
import { api, createPluginSocket } from "../api/client";

interface PluginEntry {
  plugin: Plugin;
  logs: PluginLogLine[];
  socket: WebSocket | null;
}

interface Store {
  plugins: Record<string, PluginEntry>;
  loaded: boolean;

  loadPlugins: () => Promise<void>;
  createPlugin: (name: string, code: string) => Promise<string>;
  updatePlugin: (id: string, body: { name?: string; code?: string }) => Promise<void>;
  deletePlugin: (id: string) => Promise<void>;
  startPlugin: (id: string) => Promise<void>;
  stopPlugin: (id: string) => Promise<void>;
  restartPlugin: (id: string) => Promise<void>;
  clearLogs: (id: string) => Promise<void>;
  subscribe: (id: string) => Promise<void>;
  unsubscribe: (id: string) => void;
}

export const usePluginStore = create<Store>((set, get) => ({
  plugins: {},
  loaded: false,

  loadPlugins: async () => {
    const list = await api.plugins.list();
    set((s) => {
      const next: Record<string, PluginEntry> = {};
      for (const p of list) {
        const existing = s.plugins[p.id];
        next[p.id] = existing
          ? { ...existing, plugin: p }
          : { plugin: p, logs: [], socket: null };
      }
      return { plugins: next, loaded: true };
    });
  },

  createPlugin: async (name, code) => {
    const p = await api.plugins.create(name, code);
    set((s) => ({
      plugins: {
        ...s.plugins,
        [p.id]: { plugin: p, logs: [], socket: null },
      },
    }));
    return p.id;
  },

  updatePlugin: async (id, body) => {
    const p = await api.plugins.update(id, body);
    set((s) => {
      const entry = s.plugins[id];
      if (!entry) return s;
      return {
        plugins: { ...s.plugins, [id]: { ...entry, plugin: p } },
      };
    });
  },

  deletePlugin: async (id) => {
    get().unsubscribe(id);
    await api.plugins.delete(id);
    set((s) => {
      const next = { ...s.plugins };
      delete next[id];
      return { plugins: next };
    });
  },

  startPlugin: async (id) => {
    const p = await api.plugins.start(id);
    applyPlugin(set, id, p);
  },
  stopPlugin: async (id) => {
    const p = await api.plugins.stop(id);
    applyPlugin(set, id, p);
  },
  restartPlugin: async (id) => {
    const p = await api.plugins.restart(id);
    applyPlugin(set, id, p);
  },

  clearLogs: async (id) => {
    await api.plugins.clearLogs(id);
    set((s) => {
      const entry = s.plugins[id];
      if (!entry) return s;
      return {
        plugins: { ...s.plugins, [id]: { ...entry, logs: [] } },
      };
    });
  },

  subscribe: async (id) => {
    const existing = get().plugins[id];
    if (existing?.socket) return;

    if (!existing) {
      const p = await api.plugins.get(id);
      set((s) => ({
        plugins: {
          ...s.plugins,
          [id]: { plugin: p, logs: [], socket: null },
        },
      }));
    }

    const socket = createPluginSocket(id);

    set((s) => {
      const entry = s.plugins[id];
      if (!entry) return s;
      return {
        plugins: { ...s.plugins, [id]: { ...entry, socket, logs: [] } },
      };
    });

    socket.onmessage = (e) => {
      const frame = JSON.parse(e.data) as PluginWsFrame;
      set((s) => {
        const entry = s.plugins[id];
        if (!entry) return s;
        if (frame.type === "plugin_state") {
          return {
            plugins: { ...s.plugins, [id]: { ...entry, plugin: frame.data } },
          };
        }
        if (frame.type === "log") {
          return {
            plugins: {
              ...s.plugins,
              [id]: { ...entry, logs: [...entry.logs, frame.data] },
            },
          };
        }
        if (frame.type === "status") {
          const updated: Plugin = {
            ...entry.plugin,
            status: frame.data.status,
            last_error: frame.data.error ?? entry.plugin.last_error,
          };
          return {
            plugins: { ...s.plugins, [id]: { ...entry, plugin: updated } },
          };
        }
        if (frame.type === "logs_cleared") {
          return {
            plugins: { ...s.plugins, [id]: { ...entry, logs: [] } },
          };
        }
        return s;
      });
    };

    socket.onclose = () => {
      set((s) => {
        const entry = s.plugins[id];
        if (!entry || entry.socket !== socket) return s;
        return {
          plugins: { ...s.plugins, [id]: { ...entry, socket: null } },
        };
      });
    };
  },

  unsubscribe: (id) => {
    const entry = get().plugins[id];
    if (entry?.socket) {
      entry.socket.close();
    }
  },
}));

function applyPlugin(
  set: (fn: (s: { plugins: Record<string, PluginEntry> }) => Partial<{
    plugins: Record<string, PluginEntry>;
  }>) => void,
  id: string,
  p: Plugin,
) {
  set((s) => {
    const entry = s.plugins[id];
    if (!entry) return s;
    return {
      plugins: { ...s.plugins, [id]: { ...entry, plugin: p } },
    };
  });
}
