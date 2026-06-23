// WebSocket client for live streaming + Agent Monitor events.
// Connects to the gateway /ws (built out in Phase 6.2); degrades gracefully
// (auto-reconnect) when the backend WS isn't up yet.
import { API_BASE } from "./client";
import { useStore } from "../store";

function wsUrl(): string {
  return API_BASE.replace(/^http/, "ws") + "/ws";
}

let socket: WebSocket | null = null;
let reconnectTimer: number | undefined;

export function connectWs(): void {
  if (socket && socket.readyState <= WebSocket.OPEN) return;
  try {
    socket = new WebSocket(wsUrl());
  } catch {
    scheduleReconnect();
    return;
  }

  socket.onopen = () => useStore.getState().setWsConnected(true);
  socket.onclose = () => {
    useStore.getState().setWsConnected(false);
    scheduleReconnect();
  };
  socket.onerror = () => socket?.close();
  socket.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data as string);
      useStore.getState().pushAgentEvent({
        ts: Date.now(),
        type: data.type ?? "event",
        agent: data.agent_name ?? data.agent,
        status: data.status,
        summary: data.summary ?? (typeof data.text === "string" ? data.text.slice(0, 80) : undefined),
        payload: data.payload ?? data,
      });
    } catch {
      /* ignore malformed frames */
    }
  };
}

function scheduleReconnect(): void {
  window.clearTimeout(reconnectTimer);
  reconnectTimer = window.setTimeout(connectWs, 4000);
}
