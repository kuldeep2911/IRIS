// Chat page: message stream, mic, tool-call cards, optional avatar pane.
// Replies are revealed token-by-token (real backend token streaming arrives
// with the Phase 6.2 WebSocket).
import { useEffect, useRef, useState } from "react";
import { sendChat } from "../api/client";
import { useStore } from "../store";
import ChatMessage from "../components/ChatMessage";
import MicButton from "../components/MicButton";
import Avatar from "../components/Avatar";

let counter = 0;
const newId = () => `m${Date.now()}_${counter++}`;

export default function Chat() {
  const { messages, addMessage, updateMessage, avatarEnabled, setAvatarState } = useStore();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string | undefined>(undefined);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function reveal(id: string, full: string) {
    const words = full.split(" ");
    let acc = "";
    for (const w of words) {
      acc += (acc ? " " : "") + w;
      updateMessage(id, { content: acc, streaming: true });
      await new Promise((r) => setTimeout(r, 18));
    }
    updateMessage(id, { streaming: false });
  }

  async function submit(text: string) {
    const msg = text.trim();
    if (!msg || busy) return;
    setInput("");
    setBusy(true);
    addMessage({ id: newId(), role: "user", content: msg });

    const assistantId = newId();
    addMessage({ id: assistantId, role: "assistant", content: "", streaming: true });
    setAvatarState("thinking");
    try {
      const res = await sendChat(msg, sessionRef.current);
      sessionRef.current = res.session_id ?? sessionRef.current;
      updateMessage(assistantId, { model: res.model, requestClass: res.request_class });
      setAvatarState("speaking");
      await reveal(assistantId, res.reply);
      setAvatarState("success");
    } catch (e) {
      updateMessage(assistantId, { content: `⚠ ${(e as Error).message}`, streaming: false });
      setAvatarState("concern");
    } finally {
      setBusy(false);
      setTimeout(() => setAvatarState("idle"), 1200);
    }
  }

  return (
    <div className="flex h-full">
      <div className="flex flex-1 flex-col">
        <div className="flex-1 space-y-3 overflow-y-auto p-6">
          {messages.length === 0 && (
            <div className="mt-20 text-center text-gray-500">
              Ask I.R.I.S. anything — it can browse, remember, and act via MCP tools.
            </div>
          )}
          {messages.map((m) => (
            <ChatMessage key={m.id} msg={m} />
          ))}
          <div ref={endRef} />
        </div>
        <form
          className="flex items-center gap-2 border-t border-white/10 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit(input);
          }}
        >
          <MicButton onText={(t) => void submit(t)} />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Message IRIS…"
            className="flex-1 rounded-xl bg-white/5 px-4 py-2 outline-none placeholder:text-gray-600"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-iris-accent px-4 py-2 font-medium text-white disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>

      {avatarEnabled && (
        <div className="hidden w-80 shrink-0 border-l border-white/10 p-4 lg:block">
          <div className="h-72">
            <Avatar />
          </div>
          <p className="mt-3 text-center text-xs text-gray-500">IRIS</p>
        </div>
      )}
    </div>
  );
}
