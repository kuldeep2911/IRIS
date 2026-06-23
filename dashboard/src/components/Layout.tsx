// App shell: left nav + routed content. Dark theme.
import { NavLink, Outlet } from "react-router-dom";
import { useStore } from "../store";

const NAV = [
  { to: "/", label: "Chat", end: true },
  { to: "/agents", label: "Agent Monitor" },
  { to: "/memory", label: "Memory" },
  { to: "/connections", label: "Connections" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  const wsConnected = useStore((s) => s.wsConnected);
  return (
    <div className="flex h-screen bg-iris-bg text-gray-200">
      <aside className="w-56 shrink-0 border-r border-white/10 p-4 flex flex-col">
        <div className="text-2xl font-bold mb-6">
          I.R.I.S. <span className="text-iris-cyan">v5</span>
        </div>
        <nav className="space-y-1 flex-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm transition ${
                  isActive ? "bg-iris-accent/20 text-white" : "text-gray-400 hover:bg-white/5"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span
            className={`h-2 w-2 rounded-full ${wsConnected ? "bg-emerald-400" : "bg-gray-600"}`}
          />
          {wsConnected ? "live" : "offline"}
        </div>
      </aside>
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
