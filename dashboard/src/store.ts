// IRIS dashboard global state (Zustand). Holds chat messages, the live agent
// event log (Agent Monitor), WebSocket status, and UI settings.
import { create } from "zustand";

export type Role = "user" | "assistant";

export interface ToolCall {
  name: string;
  status?: "ok" | "error" | "denied" | "running";
  args?: unknown;
}

export interface ChatMsg {
  id: string;
  role: Role;
  content: string;
  model?: string;
  requestClass?: string;
  tools?: ToolCall[];
  streaming?: boolean;
}

export interface AgentEvent {
  ts: number;
  type: string; // agent_start | agent_update | agent_complete | tool_result | confirm_request | final
  agent?: string;
  summary?: string;
  payload?: unknown;
}

export type AvatarState = "idle" | "thinking" | "speaking" | "success" | "concern";

interface Store {
  messages: ChatMsg[];
  agentEvents: AgentEvent[];
  wsConnected: boolean;
  avatarEnabled: boolean;
  avatarState: AvatarState;

  addMessage: (m: ChatMsg) => void;
  updateMessage: (id: string, patch: Partial<ChatMsg>) => void;
  pushAgentEvent: (e: AgentEvent) => void;
  clearAgentEvents: () => void;
  setWsConnected: (b: boolean) => void;
  setAvatarEnabled: (b: boolean) => void;
  setAvatarState: (s: AvatarState) => void;
}

const AVATAR_KEY = "iris.avatarEnabled";
const initialAvatar = ((): boolean => {
  try {
    return localStorage.getItem(AVATAR_KEY) !== "false";
  } catch {
    return true;
  }
})();

export const useStore = create<Store>((set) => ({
  messages: [],
  agentEvents: [],
  wsConnected: false,
  avatarEnabled: initialAvatar,
  avatarState: "idle",

  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  updateMessage: (id, patch) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),
  pushAgentEvent: (e) => set((s) => ({ agentEvents: [...s.agentEvents.slice(-200), e] })),
  clearAgentEvents: () => set({ agentEvents: [] }),
  setWsConnected: (b) => set({ wsConnected: b }),
  setAvatarEnabled: (b) => {
    try {
      localStorage.setItem(AVATAR_KEY, String(b));
    } catch {
      /* ignore */
    }
    set({ avatarEnabled: b });
  },
  setAvatarState: (s2) => set({ avatarState: s2 }),
}));
