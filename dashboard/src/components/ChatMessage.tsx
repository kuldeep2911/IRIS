// A single chat bubble (user or assistant) with optional tool-call cards.
import type { ChatMsg } from "../store";
import ToolCallCard from "./ToolCallCard";

export default function ChatMessage({ msg }: { msg: ChatMsg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        {msg.tools && msg.tools.length > 0 && (
          <div className="w-full">
            {msg.tools.map((t, i) => (
              <ToolCallCard key={i} tool={t} />
            ))}
          </div>
        )}
        <div
          className={`rounded-2xl px-4 py-2 text-sm ${
            isUser ? "bg-iris-accent text-white" : "bg-white/5 text-gray-100"
          }`}
        >
          {msg.content}
          {msg.streaming && <span className="ml-0.5 animate-pulse">▋</span>}
        </div>
        {msg.model && (
          <div className="mt-0.5 text-[10px] text-gray-500">
            {msg.model}
            {msg.requestClass ? ` · ${msg.requestClass}` : ""}
          </div>
        )}
      </div>
    </div>
  );
}
