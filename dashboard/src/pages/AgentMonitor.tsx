// Agent Monitor — live agent chain + tool calls over WebSocket (Phase 6.2).
import { useStore } from "../store";
import AgentLog from "../components/AgentLog";

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

      <div className="flex-1 overflow-y-auto">
        {agentEvents.length === 0 ? (
          <div className="text-gray-600">
            No activity yet. Run a complex task in Chat to watch the commander delegate to
            specialists live (Commander → specialist → MCP call → review → result).
          </div>
        ) : (
          <AgentLog />
        )}
      </div>
    </div>
  );
}
