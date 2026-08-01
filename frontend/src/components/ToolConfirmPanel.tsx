import { useState } from "react";
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
