import { create } from "zustand";
import type { SessionStatus } from "../api/types";

export type BrowserNotificationPermission = NotificationPermission | "unsupported";

export function getBrowserNotificationPermission(): BrowserNotificationPermission {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return "unsupported";
  }
  return Notification.permission;
}

export async function requestBrowserNotificationPermission(): Promise<BrowserNotificationPermission> {
  if (getBrowserNotificationPermission() === "unsupported") {
    return "unsupported";
  }
  return Notification.requestPermission();
}

function showBrowserNotification(toast: AppToast): void {
  if (getBrowserNotificationPermission() !== "granted") return;

  const notification = new Notification(toast.title, {
    body: toast.message,
    tag: toast.id,
  });

  notification.onclick = () => {
    window.focus();
    window.location.assign(`/console/${toast.sessionId}`);
    notification.close();
  };
}

export interface AppToast {
  id: string;
  sessionId: string;
  title: string;
  message: string;
  status: Extract<SessionStatus, "WAITING_USER" | "WAITING_CONFIRM">;
  createdAt: number;
  confirm?: {
    callId: string;
    toolName: string;
    args: unknown;
  };
}

interface ToastStore {
  toasts: AppToast[];
  upsertToast: (toast: Omit<AppToast, "createdAt">) => void;
  dismissToast: (id: string) => void;
  dismissSessionToasts: (sessionId: string) => void;
}

const MAX_TOASTS = 5;

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],

  upsertToast: (toast) =>
    set((s) => {
      const nextToast: AppToast = { ...toast, createdAt: Date.now() };
      const withoutDuplicate = s.toasts.filter((t) => t.id !== toast.id);

      showBrowserNotification(nextToast);

      return {
        toasts: [nextToast, ...withoutDuplicate].slice(0, MAX_TOASTS),
      };
    }),

  dismissToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((toast) => toast.id !== id) })),

  dismissSessionToasts: (sessionId) =>
    set((s) => ({
      toasts: s.toasts.filter((toast) => toast.sessionId !== sessionId),
    })),
}));
