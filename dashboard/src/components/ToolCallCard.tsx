// A collapsible card shown between chat messages for each MCP tool call.
import { useState } from "react";
import type { ToolCall } from "../store";

const STATUS_DOT: Record<string, string> = {
  ok: "bg-emerald-400",
  error: "bg-red-400",
  denied: "bg-amber-400",
  running: "bg-cyan-400 animate-pulse",
};

export default function ToolCallCard({ tool }: { tool: ToolCall }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1 rounded-lg border border-white/10 bg-white/5 text-xs">
      <button
        className="flex w-full items-center gap-2 px-3 py-1.5"
        onClick={() => setOpen((o) => !o)}
      >
        <span className={`h-2 w-2 rounded-full ${STATUS_DOT[tool.status ?? "ok"]}`} />
        <span className="font-mono text-cyan-300">{tool.name}</span>
        <span className="ml-auto text-gray-500">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <pre className="overflow-x-auto px-3 pb-2 text-gray-400">
          {JSON.stringify(tool.args ?? {}, null, 2)}
        </pre>
      )}
    </div>
  );
}
