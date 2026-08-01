import { useMemo } from "react";

export function formatYamlValue(value: unknown, indent = 0): string {
  const pad = "  ".repeat(indent);

  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") {
    return value.includes("\n")
      ? `|\n${value
          .split("\n")
          .map((line) => `${pad}  ${line}`)
          .join("\n")}`
      : JSON.stringify(value);
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

interface ToolPreviewProps {
  name: string;
  args: unknown;
  className?: string;
}

export default function ToolPreview({ name, args, className = "mt-2" }: ToolPreviewProps) {
  const preview = useMemo(() => {
    if (typeof args !== "object" || args === null) {
      return null;
    }

    const argsObj = args as Record<string, unknown>;

    if (name === "write" && typeof argsObj.file_path === "string") {
      const content = typeof argsObj.content === "string" ? argsObj.content : "";
      return {
        type: "write" as const,
        path: argsObj.file_path,
        content,
      };
    }

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
      <div className={`${className} flex flex-col gap-2`}>
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
      <div className={`${className} flex flex-col gap-2`}>
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
      <div className={`${className} flex flex-col gap-2`}>
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
