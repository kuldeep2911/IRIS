// Agent Monitor — live chain of agent/tool events over WebSocket (Phase 6.2).
import { useStore } from "../store";

export default function AgentMonitor() {
  const { agentEvents, wsConnected, clearAgentEvents } = useStore();
  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-xl font-semibold">Agent Monitor</h1>
        <span className={`text-xs ${wsConnected ? "text-emerald-400" : "text-gray-500"}`}>
          {wsConnected ? "● live" : "○ waiting for stream"}
        </span>
        <button
          onClick={clearAgentEvents}
          className="ml-auto rounded-lg bg-white/5 px-3 py-1 text-xs hover:bg-white/10"
        >
          Clear
        </button>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto font-mono text-xs">
        {agentEvents.length === 0 && (
          <div className="text-gray-600">
            No activity yet. Run a task in Chat to see the agent chain stream here.
          </div>
        )}
        {agentEvents.map((e, i) => (
          <div key={i} className="flex gap-3 rounded border border-white/5 px-3 py-1">
            <span className="text-gray-600">{new Date(e.ts).toLocaleTimeString()}</span>
            <span className="text-cyan-300">{e.type}</span>
            {e.agent && <span className="text-iris-accent">{e.agent}</span>}
            <span className="text-gray-400">{e.summary}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
