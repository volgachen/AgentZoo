import { NavLink, Outlet } from "react-router-dom";
import { useStore } from "./store/sessions";

const NAV = [
  { to: "/", label: "Agent Registry", end: true },
  { to: "/sessions", label: "Sessions" },
];

export default function App() {
  const sessions = useStore((s) => s.sessions);
  const count = Object.keys(sessions).length;

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      {/* Top nav */}
      <nav className="border-b border-gray-800 px-6 py-3 flex items-center gap-6">
        <span className="font-semibold text-white tracking-tight">AgentZoo</span>
        <div className="flex gap-1">
          {NAV.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-gray-800 text-white"
                    : "text-gray-400 hover:text-white hover:bg-gray-800/50"
                }`
              }
            >
              {label}
              {label === "Sessions" && count > 0 && (
                <span className="ml-1.5 text-xs bg-indigo-700 text-white px-1.5 py-0.5 rounded-full">
                  {count}
                </span>
              )}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* Page content */}
      <main className="flex-1 flex flex-col min-h-0">
        <Outlet />
      </main>
    </div>
  );
}
