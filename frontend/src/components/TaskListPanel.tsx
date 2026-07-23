import type { Task, TaskStatus } from "../api/types";

// Glyph + color per task status, matching the dark palette used elsewhere.
const STATUS_GLYPH: Record<TaskStatus, { icon: string; style: string }> = {
  pending: { icon: "○", style: "text-gray-500" },
  in_progress: { icon: "◐", style: "text-blue-400" },
  completed: { icon: "✓", style: "text-green-500" },
};

function TaskRow({ task }: { task: Task }) {
  const { icon, style } = STATUS_GLYPH[task.status];
  // While running, the agent's active_form ("Searching the codebase…") reads
  // better than the imperative subject.
  const label =
    task.status === "in_progress" && task.active_form
      ? task.active_form
      : task.subject;
  const blocked = task.blocked_by.length > 0;
  return (
    <li className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-gray-800/40">
      <span className={`select-none font-mono text-sm leading-5 ${style}`}>
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p
          className={`text-xs leading-5 break-words ${
            task.status === "completed"
              ? "text-gray-500 line-through"
              : "text-gray-200"
          }`}
        >
          <span className="text-gray-600 font-mono">#{task.id} </span>
          {label}
        </p>
        {blocked && (
          <p className="text-[10px] text-amber-500/80 mt-0.5">
            blocked by {task.blocked_by.map((b) => `#${b}`).join(", ")}
          </p>
        )}
      </div>
    </li>
  );
}

export default function TaskListPanel({ tasks }: { tasks: Task[] }) {
  // Stable order: by numeric id so the list doesn't reshuffle as statuses flip.
  const sorted = [...tasks].sort((a, b) => Number(a.id) - Number(b.id));
  const done = sorted.filter((t) => t.status === "completed").length;

  return (
    <section className="flex-1 flex flex-col min-h-0">
      <div className="shrink-0 flex items-center justify-between px-2 pb-1.5">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
          Tasks
        </h2>
        {sorted.length > 0 && (
          <span className="text-[10px] text-gray-500 font-mono">
            {done}/{sorted.length}
          </span>
        )}
      </div>
      {sorted.length === 0 ? (
        <p className="px-2 text-xs text-gray-600">No tasks yet.</p>
      ) : (
        <ul className="flex flex-col gap-0.5 overflow-y-auto min-h-0">
          {sorted.map((t) => (
            <TaskRow key={t.id} task={t} />
          ))}
        </ul>
      )}
    </section>
  );
}
