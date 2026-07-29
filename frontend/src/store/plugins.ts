import { create } from "zustand";
import type {
  PluginDefinition,
  PluginInstance,
  PluginLogLine,
  PluginRun,
  PluginWsFrame,
} from "../api/types";
import { api, createPluginSocket } from "../api/client";
import type { CreatePluginInstancePayload, UpdatePluginInstancePayload } from "../api/client";

interface Store {
  catalog: PluginDefinition[];
  instances: Record<string, PluginInstance>;
  runsByInstance: Record<string, PluginRun[]>;
  logsByInstance: Record<string, PluginLogLine[]>;
  sockets: Record<string, WebSocket | null>;
  loaded: boolean;

  loadPlugins: () => Promise<void>;
  loadRuns: (instanceId: string) => Promise<void>;
  loadInstanceLogs: (instanceId: string, limit?: number) => Promise<void>;
  loadRunLogs: (runId: string, limit?: number) => Promise<PluginLogLine[]>;
  createInstance: (body: CreatePluginInstancePayload) => Promise<string>;
  updateInstance: (id: string, body: UpdatePluginInstancePayload) => Promise<void>;
  deleteInstance: (id: string) => Promise<void>;
  startInstance: (id: string) => Promise<void>;
  stopInstance: (id: string) => Promise<void>;
  restartInstance: (id: string) => Promise<void>;
  subscribe: (id: string) => Promise<void>;
  unsubscribe: (id: string) => void;
}

export const ACTIVE_PLUGIN_STATUSES = new Set([
  "starting",
  "waiting_input",
  "running",
  "stopping",
]);

export const usePluginStore = create<Store>((set, get) => ({
  catalog: [],
  instances: {},
  runsByInstance: {},
  logsByInstance: {},
  sockets: {},
  loaded: false,

  loadPlugins: async () => {
    const [catalog, instances] = await Promise.all([
      api.plugins.catalog(),
      api.plugins.instances(),
    ]);
    set((s) => {
      const nextInstances: Record<string, PluginInstance> = {};
      const nextSockets: Record<string, WebSocket | null> = {};
      for (const instance of instances) {
        nextInstances[instance.id] = instance;
        nextSockets[instance.id] = s.sockets[instance.id] ?? null;
      }
      return {
        catalog,
        instances: nextInstances,
        sockets: nextSockets,
        loaded: true,
      };
    });
  },

  loadRuns: async (instanceId) => {
    const runs = await api.plugins.runs(instanceId);
    set((s) => ({
      runsByInstance: { ...s.runsByInstance, [instanceId]: runs },
    }));
  },

  loadInstanceLogs: async (instanceId, limit = 200) => {
    const logs = await api.plugins.instanceLogs(instanceId, limit);
    set((s) => ({
      logsByInstance: { ...s.logsByInstance, [instanceId]: logs },
    }));
  },

  loadRunLogs: async (runId, limit = 1000) => api.plugins.runLogs(runId, limit),

  createInstance: async (body) => {
    const instance = await api.plugins.createInstance(body);
    set((s) => ({
      instances: { ...s.instances, [instance.id]: instance },
      sockets: { ...s.sockets, [instance.id]: null },
    }));
    return instance.id;
  },

  updateInstance: async (id, body) => {
    const instance = await api.plugins.updateInstance(id, body);
    applyInstance(set, instance);
  },

  deleteInstance: async (id) => {
    get().unsubscribe(id);
    await api.plugins.deleteInstance(id);
    set((s) => {
      const instances = { ...s.instances };
      const runsByInstance = { ...s.runsByInstance };
      const logsByInstance = { ...s.logsByInstance };
      const sockets = { ...s.sockets };
      delete instances[id];
      delete runsByInstance[id];
      delete logsByInstance[id];
      delete sockets[id];
      return { instances, runsByInstance, logsByInstance, sockets };
    });
  },

  startInstance: async (id) => {
    await api.plugins.startInstance(id);
    const instance = await api.plugins.instance(id);
    applyInstance(set, instance);
    void get().loadRuns(id);
  },

  stopInstance: async (id) => {
    const instance = await api.plugins.stopInstance(id);
    applyInstance(set, instance);
    void get().loadRuns(id);
  },

  restartInstance: async (id) => {
    await api.plugins.restartInstance(id);
    const instance = await api.plugins.instance(id);
    applyInstance(set, instance);
    void get().loadRuns(id);
  },

  subscribe: async (id) => {
    const existingSocket = get().sockets[id];
    if (existingSocket) return;

    if (!get().instances[id]) {
      const instance = await api.plugins.instance(id);
      applyInstance(set, instance);
    }

    const socket = createPluginSocket(id);
    set((s) => ({
      sockets: { ...s.sockets, [id]: socket },
      logsByInstance: { ...s.logsByInstance, [id]: [] },
    }));

    socket.onmessage = (e) => {
      const frame = JSON.parse(e.data) as PluginWsFrame;
      set((s) => {
        const instance = s.instances[id];
        if (!instance && frame.type !== "plugin_instance_state") return s;

        if (frame.type === "plugin_instance_state") {
          return {
            instances: { ...s.instances, [id]: frame.data },
          };
        }
        if (frame.type === "log") {
          const current = s.logsByInstance[id] ?? [];
          return {
            logsByInstance: {
              ...s.logsByInstance,
              [id]: [...current, frame.data].slice(-2000),
            },
          };
        }
        if (frame.type === "status") {
          const current = s.instances[id];
          if (!current) return s;
          return {
            instances: {
              ...s.instances,
              [id]: {
                ...current,
                status: frame.data.status,
                current_run_id: frame.data.run_id ?? current.current_run_id,
              },
            },
          };
        }
        if (frame.type === "logs_cleared") {
          return {
            logsByInstance: { ...s.logsByInstance, [id]: [] },
          };
        }
        return s;
      });
    };

    socket.onclose = () => {
      set((s) => {
        if (s.sockets[id] !== socket) return s;
        return { sockets: { ...s.sockets, [id]: null } };
      });
    };
  },

  unsubscribe: (id) => {
    const socket = get().sockets[id];
    if (socket) socket.close();
  },
}));

function applyInstance(
  set: (fn: (s: Store) => Partial<Store>) => void,
  instance: PluginInstance,
) {
  set((s) => ({
    instances: { ...s.instances, [instance.id]: instance },
  }));
}
