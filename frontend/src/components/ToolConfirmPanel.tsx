import { useMemo, useState } from "react";

interface ToolConfirmPanelProps {
  name: string;
  args: unknown;
  callId: string;
  onApprove: (message?: string) => void;
  onDeny: (message?: string) => void;
}

function toOneLine(s: string, max = 120): string {
  const flat = s.replace(/\s+/g, " ").trim();
  return flat.length > max ? flat.slice(0, max) + "…" : flat;
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
      <code className="block font-mono text-xs text-orange-200 bg-gray-950/60 border border-gray-800 rounded px-2 py-1.5 mt-2 overflow-x-auto">
        {name}({toOneLine(JSON.stringify(args), 200)})
      </code>
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
      className="flex flex-col gap-2 bg-orange-950/40 border border-orange-800/60 rounded-lg px-3 py-3"
    >
      <div className="flex items-center gap-3">
        <span className="text-orange-300 text-sm font-medium shrink-0">
          ⚠ Approve tool
        </span>
        <div className="flex-1" />
        <button
          onClick={handleApprove}
          className="px-3 py-1 rounded-md bg-green-700 hover:bg-green-600 text-white text-xs font-medium shrink-0 transition-colors"
        >
          Allow
        </button>
        <button
          onClick={handleDeny}
          className="px-3 py-1 rounded-md bg-red-800 hover:bg-red-700 text-white text-xs font-medium shrink-0 transition-colors"
        >
          Deny
        </button>
      </div>
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
    </div>
  );
}
