// Connections page — connect 20+ third-party apps (OpenHuman-style grid).
// OAuth opens in a popup that postMessages back; PAT/api_key uses an inline modal.
import { useEffect, useMemo, useState } from "react";
import {
  beginConnect,
  connectorStatus,
  disconnectConnector,
  getConnectors,
  submitToken,
  type ConnectorInfo,
} from "../api/client";

const CATEGORY_GROUPS: { key: string; label: string }[] = [
  { key: "communication", label: "Communication" },
  { key: "dev", label: "Dev / Code" },
  { key: "productivity", label: "Productivity" },
  { key: "storage", label: "Storage" },
  { key: "data", label: "Data / Ops" },
];

export default function Connections() {
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [toast, setToast] = useState<string | null>(null);
  const [tokenModal, setTokenModal] = useState<ConnectorInfo | null>(null);

  const refresh = async () => setConnectors(await getConnectors());

  useEffect(() => {
    refresh().catch(() => setToast("Could not load connectors"));
  }, []);

  // listen for the OAuth popup's postMessage
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      const d = e.data;
      if (d && d.type === "iris-connector") {
        if (d.status === "connected") {
          setToast(`Connected ${d.connector}`);
          void refresh();
        } else if (d.status === "error") {
          setToast(`Connect failed: ${d.detail || "error"}`);
        }
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const filtered = useMemo(() => {
    return connectors.filter(
      (c) =>
        (category === "all" || c.category === category) &&
        (c.name.toLowerCase().includes(query.toLowerCase()) || c.id.includes(query.toLowerCase())),
    );
  }, [connectors, query, category]);

  async function onConnect(c: ConnectorInfo) {
    if (c.auth_type === "oauth2") {
      const r = await beginConnect(c.id);
      if (!r.authorize_url) {
        setToast(`Cannot start OAuth for ${c.name} (check client id/secret env)`);
        return;
      }
      const popup = window.open(r.authorize_url, "iris-oauth", "width=600,height=720");
      if (!popup) {
        // popup blocked -> full-page redirect fallback
        setToast("Popup blocked — redirecting…");
        window.location.href = r.authorize_url;
        return;
      }
      pollStatus(c.id);
    } else {
      setTokenModal(c); // PAT / api_key modal
    }
  }

  async function pollStatus(id: string, tries = 0) {
    if (tries > 40) return;
    const s = await connectorStatus(id);
    if (s.status === "connected" || s.status === "error") {
      await refresh();
      return;
    }
    setTimeout(() => pollStatus(id, tries + 1), 1500);
  }

  async function onDisconnect(c: ConnectorInfo) {
    if (!confirm(`Disconnect ${c.name}?`)) return;
    await disconnectConnector(c.id);
    setToast(`Disconnected ${c.name}`);
    await refresh();
  }

  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-xl font-semibold">Connections</h1>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search apps…"
          className="ml-auto w-56 rounded-lg bg-white/5 px-3 py-1 text-sm outline-none"
        />
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {[{ key: "all", label: "All" }, ...CATEGORY_GROUPS].map((g) => (
          <button
            key={g.key}
            onClick={() => setCategory(g.key)}
            className={`rounded-full px-3 py-1 text-xs ${
              category === g.key ? "bg-iris-accent text-white" : "bg-white/5 text-gray-400"
            }`}
          >
            {g.label}
          </button>
        ))}
      </div>

      <div className="grid flex-1 grid-cols-2 gap-3 overflow-y-auto md:grid-cols-3 lg:grid-cols-4">
        {filtered.map((c) => (
          <ConnectorCard key={c.id} c={c} onConnect={() => onConnect(c)} onDisconnect={() => onDisconnect(c)} />
        ))}
      </div>

      {tokenModal && (
        <TokenModal
          connector={tokenModal}
          onClose={() => setTokenModal(null)}
          onDone={async () => {
            setTokenModal(null);
            await refresh();
          }}
          onToast={setToast}
        />
      )}
      {toast && (
        <div
          className="fixed bottom-6 right-6 rounded-lg bg-white/10 px-4 py-2 text-sm"
          onAnimationEnd={() => setToast(null)}
        >
          {toast}
        </div>
      )}
    </div>
  );
}

function ConnectorCard({
  c,
  onConnect,
  onDisconnect,
}: {
  c: ConnectorInfo;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  const connected = c.status === "connected";
  const error = c.status === "error";
  return (
    <div className="flex flex-col rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-xs">
          {c.name.slice(0, 2)}
        </span>
        <div>
          <div className="font-medium">{c.name}</div>
          <div className="text-[10px] uppercase tracking-wide text-gray-500">{c.category}</div>
        </div>
      </div>
      <div className="mt-3 flex-1 text-xs text-gray-400">
        {connected && (
          <span className="flex items-center gap-1 text-emerald-400">
            <span className="h-2 w-2 rounded-full bg-emerald-400" /> {c.account_label || "connected"}
          </span>
        )}
        {error && <span className="text-red-400">{c.last_error || "needs reconnect"}</span>}
      </div>
      <div className="mt-3">
        {connected ? (
          <button onClick={onDisconnect} className="w-full rounded-lg bg-white/5 py-1.5 text-xs hover:bg-white/10">
            Disconnect
          </button>
        ) : (
          <button onClick={onConnect} className="w-full rounded-lg bg-iris-accent py-1.5 text-xs font-medium text-white">
            {error ? "Reconnect" : "Connect"}
          </button>
        )}
      </div>
    </div>
  );
}

function TokenModal({
  connector,
  onClose,
  onDone,
  onToast,
}: {
  connector: ConnectorInfo;
  onClose: () => void;
  onDone: () => void;
  onToast: (s: string) => void;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    const r = await submitToken(connector.id, token);
    setBusy(false);
    if (r.status === "connected") {
      onToast(`Connected ${connector.name}`);
      onDone();
    } else {
      setError(r.detail || r.error || "Token rejected");
    }
  }

  return (
    <div className="fixed inset-0 grid place-items-center bg-black/60" onClick={onClose}>
      <div className="w-96 rounded-xl border border-white/10 bg-iris-bg p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold">Connect {connector.name}</h3>
        <p className="mt-1 text-xs text-gray-500">
          {connector.token_label || "API token"}
          {connector.help_url && (
            <>
              {" · "}
              <a href={connector.help_url} target="_blank" rel="noreferrer" className="text-iris-cyan">
                Where do I get this?
              </a>
            </>
          )}
        </p>
        <input
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="Paste token…"
          className="mt-3 w-full rounded-lg bg-white/5 px-3 py-2 text-sm outline-none"
        />
        {error && <div className="mt-2 text-xs text-red-400">{error}</div>}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg bg-white/5 px-3 py-1.5 text-sm">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={busy || !token}
            className="rounded-lg bg-iris-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          >
            {busy ? "Connecting…" : "Connect"}
          </button>
        </div>
      </div>
    </div>
  );
}
