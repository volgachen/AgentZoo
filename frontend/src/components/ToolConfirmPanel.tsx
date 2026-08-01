import { useMemo, useState } from "react";

interface ToolConfirmPanelProps {
  name: string;
  args: unknown;
  callId: string;
  onApprove: (message?: string) => void;
  onDeny: (message?: string) => void;
}

function formatYamlValue(value: unknown, indent = 0): string {
  const pad = "  ".repeat(indent);

  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") {
    return value.includes("\n") ? `|\n${value.split("\n").map((line) => `${pad}  ${line}`).join("\n")}` : JSON.stringify(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return value
      .map((item) => {
        if (typeof item === "object" && item !== null) {
          return `${pad}- ${formatYamlValue(item, indent + 1).trimStart()}`;
        }
        return `${pad}- ${formatYamlValue(item, indent + 1)}`;
      })
      .join("\n");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "{}";
    return entries
      .map(([key, item]) => {
        if (typeof item === "object" && item !== null) {
          return `${pad}${key}:\n${formatYamlValue(item, indent + 1)}`;
        }
        return `${pad}${key}: ${formatYamlValue(item, indent + 1)}`;
      })
      .join("\n");
  }

  return JSON.stringify(value);
}

// Parse args for write/edit tools and render specialized previews
function ToolPreview({ name, args }: { name: string; args: unknown }) {
  const preview = useMemo(() => {
    if (typeof args !== "object" || args === null) {
      return null;
    }

    const argsObj = args as Record<string, unknown>;

    // write tool: show file path + content preview
    if (name === "write" && typeof argsObj.file_path === "string") {
      const content =
        typeof argsObj.content === "string" ? argsObj.content : "";
      return {
        type: "write" as const,
        path: argsObj.file_path,
        content,
      };
    }

    // edit tool: show file path + old vs new side-by-side
    if (
      name === "edit" &&
      typeof argsObj.file_path === "string" &&
      typeof argsObj.old_string === "string" &&
      typeof argsObj.new_string === "string"
    ) {
      return {
        type: "edit" as const,
        path: argsObj.file_path,
        oldString: argsObj.old_string,
        newString: argsObj.new_string,
      };
    }

    return null;
  }, [name, args]);

  if (!preview) {
    return (
      <div className="mt-2 flex flex-col gap-2">
        <div className="text-xs text-orange-300 font-mono">
          Tool <span className="text-orange-200">{name}</span>
        </div>
        <pre className="bg-gray-950/60 border border-gray-800 rounded px-3 py-2 text-xs text-gray-300 overflow-auto max-h-64 whitespace-pre-wrap break-all">
          {formatYamlValue(args)}
        </pre>
      </div>
    );
  }

  if (preview.type === "write") {
    return (
      <div className="mt-2 flex flex-col gap-2">
        <div className="text-xs text-orange-300 font-mono">
          Write <span className="text-orange-200">{preview.path}</span>
        </div>
        <pre className="bg-gray-950/60 border border-gray-800 rounded px-3 py-2 text-xs text-gray-300 overflow-auto max-h-64 whitespace-pre-wrap break-all">
          {preview.content}
        </pre>
      </div>
    );
  }

  if (preview.type === "edit") {
    return (
      <div className="mt-2 flex flex-col gap-2">
        <div className="text-xs text-orange-300 font-mono">
          Edit <span className="text-orange-200">{preview.path}</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="flex flex-col gap-1">
            <div className="text-[10px] text-gray-500 uppercase tracking-wide px-1">
              Original
            </div>
            <pre className="bg-gray-950/60 border border-gray-800 rounded px-3 py-2 text-xs text-red-300/80 overflow-auto max-h-64 whitespace-pre-wrap break-all">
              {preview.oldString}
            </pre>
          </div>
          <div className="flex flex-col gap-1">
            <div className="text-[10px] text-gray-500 uppercase tracking-wide px-1">
              Modified
            </div>
            <pre className="bg-gray-950/60 border border-gray-800 rounded px-3 py-2 text-xs text-green-300/80 overflow-auto max-h-64 whitespace-pre-wrap break-all">
              {preview.newString}
            </pre>
          </div>
        </div>
      </div>
    );
  }

  return null;
}

export default function ToolConfirmPanel({
  name,
  args,
  callId,
  onApprove,
  onDeny,
}: ToolConfirmPanelProps) {
  const [supplementaryMessage, setSupplementaryMessage] = useState("");
  const [minimized, setMinimized] = useState(false);

  const handleApprove = () => {
    onApprove(supplementaryMessage.trim() || undefined);
    setSupplementaryMessage("");
  };

  const handleDeny = () => {
    onDeny(supplementaryMessage.trim() || undefined);
    setSupplementaryMessage("");
  };

  return (
    <div
      key={callId}
      className={`pointer-events-auto border border-orange-800/70 bg-gray-950/95 shadow-2xl backdrop-blur rounded-lg ${
        minimized ? "px-3 py-2" : "px-3 py-3"
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="min-w-0 truncate text-orange-300 text-sm font-medium shrink">
          ⚠ Tool Confirm <span className="text-orange-200">({name})</span>
        </span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => setMinimized((v) => !v)}
          className="px-2 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs font-medium shrink-0 transition-colors"
          title={minimized ? "Expand tool confirmation" : "Minimize tool confirmation"}
        >
          {minimized ? "Expand" : "Minimize"}
        </button>
        <button
          type="button"
          onClick={handleApprove}
          className="px-3 py-1 rounded-md bg-green-700 hover:bg-green-600 text-white text-xs font-medium shrink-0 transition-colors"
        >
          Allow
        </button>
        <button
          type="button"
          onClick={handleDeny}
          className="px-3 py-1 rounded-md bg-red-800 hover:bg-red-700 text-white text-xs font-medium shrink-0 transition-colors"
        >
          Deny
        </button>
      </div>

      {!minimized && (
        <>
          <ToolPreview name={name} args={args} />

          {/* Supplementary message input */}
          <div className="flex flex-col gap-1 mt-1">
            <label className="text-xs text-gray-400">
              Additional message (optional)
            </label>
            <textarea
              value={supplementaryMessage}
              onChange={(e) => setSupplementaryMessage(e.target.value)}
              placeholder="Provide additional context or instructions..."
              className="bg-gray-900/60 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none focus:border-orange-600"
              rows={2}
            />
          </div>
        </>
      )}
    </div>
  );
}
