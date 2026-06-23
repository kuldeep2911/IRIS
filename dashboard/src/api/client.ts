// REST client for the IRIS gateway.
const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

export interface ChatResponse {
  reply: string;
  model: string;
  usage: { input_tok: number; output_tok: number; total_tok: number };
  request_class: string;
  steps: number;
  session_id?: string;
}

export async function sendChat(message: string, sessionId?: string): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!res.ok) throw new Error(`chat failed: ${res.status}`);
  return (await res.json()) as ChatResponse;
}

export async function getHealth(): Promise<unknown> {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

export interface UsageReport {
  tenant_id: string;
  totals: { input_tok: number; output_tok: number; cost_usd: number };
  by_model: { model: string; input_tok: number; output_tok: number; cost_usd: number; calls: number }[];
  by_day: { day: string; cost_usd: number; tokens: number }[];
}

export async function getUsage(): Promise<UsageReport> {
  const res = await fetch(`${API_BASE}/usage`);
  if (!res.ok) throw new Error(`usage failed: ${res.status}`);
  return (await res.json()) as UsageReport;
}

export { API_BASE };
