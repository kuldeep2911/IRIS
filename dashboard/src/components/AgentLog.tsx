// AgentLog — the live Agent Monitor view: active agent card, the agent chain,
// and a collapsible tool-call log. Fed by WebSocket events in the store.
import { useMemo, useState } from "react";
import { useStore, type AgentEvent } from "../store";

const STATUS_ICON: Record<string, string> = {
  running: "⏳",
  ok: "✓",
  error: "✕",
  failed: "✕",
  denied: "⛔",
  confirm: "❔",
  blocked: "⛔",
};

function statusColor(s?: string): string {
  if (s === "ok") return "text-emerald-400";
  if (s === "error" || s === "failed" || s === "blocked" || s === "denied") return "text-red-400";
  if (s === "running") return "text-cyan-400";
  return "text-gray-400";
}

// The active agent = last agent_start whose agent has no later complete/fail.
function activeAgent(events: AgentEvent[]): AgentEvent | null {
  const done = new Set<string>();
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "agent_complete" || e.type === "agent_failed") done.add(e.agent ?? "");
    if (e.type === "agent_start" && !done.has(e.agent ?? "")) return e;
  }
  return null;
}

export default function AgentLog() {
  const events = useStore((s) => s.agentEvents);
  const [showTools, setShowTools] = useState(true);

  const active = useMemo(() => activeAgent(events), [events]);
  const toolEvents = useMemo(() => events.filter((e) => e.type === "tool_result"), [events]);

  return (
    <div className="space-y-4">
      {/* Active agent card */}
      <div className="rounded-xl border border-white/10 bg-white/5 p-4">
        <div className="text-xs uppercase tracking-wide text-gray-500">Active agent</div>
        {active ? (
          <div className="mt-1 flex items-center gap-2">
            <span className="text-cyan-400">{STATUS_ICON["running"]}</span>
            <span className="text-lg font-semibold text-white">{active.agent}</span>
            <span className="text-sm text-gray-400">{active.summary}</span>
          </div>
        ) : (
          <div className="mt-1 text-gray-500">Idle</div>
        )}
      </div>

      {/* Agent chain log */}
      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">Agent chain</div>
        <div className="space-y-1 font-mono text-xs">
          {events
            .filter((e) => e.type !== "tool_result")
            .map((e, i) => (
              <div key={i} className="flex items-center gap-2 rounded border border-white/5 px-3 py-1">
                <span className={statusColor(e.status)}>{STATUS_ICON[e.status ?? ""] ?? "•"}</span>
                <span className="text-cyan-300">{e.type}</span>
                {e.agent && <span className="text-iris-accent">{e.agent}</span>}
                <span className="truncate text-gray-400">{e.summary}</span>
              </div>
            ))}
        </div>
      </div>

      {/* Tool-call log (collapsible) */}
      <div>
        <button
          onClick={() => setShowTools((v) => !v)}
          className="mb-1 text-xs uppercase tracking-wide text-gray-500"
        >
          Tool calls ({toolEvents.length}) {showTools ? "▾" : "▸"}
        </button>
        {showTools && (
          <div className="space-y-1 font-mono text-xs">
            {toolEvents.map((e, i) => (
              <div key={i} className="flex items-center gap-2 rounded border border-white/5 px-3 py-1">
                <span className={statusColor(e.status)}>{STATUS_ICON[e.status ?? ""] ?? "•"}</span>
                {e.agent && <span className="text-iris-accent">{e.agent}</span>}
                <span className="text-gray-400">{e.summary}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
