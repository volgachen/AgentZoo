import { useEffect, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store/sessions";
import { useToastStore, type AppToast } from "../store/toasts";

function formatToolDetail(toast: AppToast): string {
  if (!toast.confirm) return "";
  return `${toast.confirm.toolName}(${JSON.stringify(toast.confirm.args, null, 2)})`;
}

const TOAST_TTL_MS = 15_000;

function ToastCard({ toast }: { toast: AppToast }) {
  const navigate = useNavigate();
  const setActiveSession = useStore((s) => s.setActiveSession);
  const resolveConfirm = useStore((s) => s.resolveConfirm);
  const dismissToast = useToastStore((s) => s.dismissToast);

  useEffect(() => {
    const timer = window.setTimeout(() => dismissToast(toast.id), TOAST_TTL_MS);
    return () => window.clearTimeout(timer);
  }, [dismissToast, toast.id]);

  const openSession = () => {
    dismissToast(toast.id);
    setActiveSession(toast.sessionId);
    navigate(`/console/${toast.sessionId}`);
  };

  const approve = (e: MouseEvent) => {
    e.stopPropagation();
    if (!toast.confirm) return;
    resolveConfirm(toast.sessionId, toast.confirm.callId, true);
    dismissToast(toast.id);
  };

  const close = (e: MouseEvent) => {
    e.stopPropagation();
    dismissToast(toast.id);
  };

  const isConfirm = toast.status === "WAITING_CONFIRM";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={openSession}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openSession();
        }
      }}
      className={`w-96 max-w-[calc(100vw-2rem)] cursor-pointer rounded-lg border bg-gray-900/95 px-4 py-3 text-left shadow-2xl backdrop-blur transition-colors hover:bg-gray-800 ${
        isConfirm ? "border-orange-700/70" : "border-blue-700/70"
      }`}
    >
      <div className="flex items-start gap-3">
        <div
          className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
            isConfirm ? "bg-orange-400" : "bg-blue-400"
          }`}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-gray-100">
            {toast.title}
          </div>
          <div className="mt-0.5 text-xs text-gray-300">{toast.message}</div>
        </div>
        <button
          type="button"
          onClick={close}
          className="shrink-0 rounded px-1 text-sm text-gray-500 hover:bg-gray-800 hover:text-gray-200"
          aria-label="Dismiss notification"
        >
          ×
        </button>
      </div>

      {toast.confirm && (
        <div className="mt-3 flex justify-end">
          <div className="group relative">
            <button
              type="button"
              onClick={approve}
              className="rounded-md bg-green-700 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-green-600"
            >
              同意执行
            </button>
            <pre className="absolute bottom-full right-0 z-50 mb-2 hidden max-h-64 w-[32rem] max-w-[calc(100vw-2rem)] overflow-auto rounded-lg border border-gray-700 bg-gray-950 p-3 font-mono text-xs text-gray-200 shadow-xl whitespace-pre-wrap break-all group-hover:block">
              {formatToolDetail(toast)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ToastCenter() {
  const currentToast = useToastStore((s) => s.toasts[0]);

  if (!currentToast) return null;

  return (
    <div className="fixed right-4 top-16 z-50">
      <ToastCard key={currentToast.id} toast={currentToast} />
    </div>
  );
}
