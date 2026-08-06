import { useState } from "react";
import { getToolSummary } from "../config/toolDisplay";
import ToolPreview from "./ToolPreview";

interface ToolConfirmPanelProps {
  name: string;
  args: unknown;
  callId: string;
  onApprove: (message?: string) => void;
  onDeny: (message?: string) => void;
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
  const summary = getToolSummary(name, args);

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
        <span className="min-w-0 truncate text-orange-300 text-sm font-medium shrink" title={`call_id: ${callId}`}>
          ⚠ Tool Confirm <span className="text-orange-200">{name}</span>
          {summary && <span className="text-gray-400 font-mono font-normal"> {summary}</span>}
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
