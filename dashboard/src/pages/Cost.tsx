// Cost page — reads the usage table (tokens + cost by model + by day), with a
// live per-tenant selector. This is the per-tenant billing view (Phase 8.2).
import { useEffect, useState } from "react";
import { getTenants, getUsage, type TenantInfo, type UsageReport } from "../api/client";

const usd = (n: number) => `$${n.toFixed(4)}`;
const num = (n: number) => n.toLocaleString();

export default function Cost() {
  const [tenants, setTenants] = useState<TenantInfo[]>([]);
  const [tenant, setTenant] = useState<string>("");
  const [data, setData] = useState<UsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTenants()
      .then((ts) => {
        setTenants(ts);
        if (ts.length && !tenant) setTenant(ts[0].id);
      })
      .catch(() => {/* selector is optional */});
  }, []);

  useEffect(() => {
    setData(null);
    getUsage(tenant || undefined)
      .then(setData)
      .catch((e) => setError((e as Error).message));
  }, [tenant]);

  if (error) return <div className="p-6 text-red-400">Failed to load usage: {error}</div>;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Cost &amp; usage</h1>
        {tenants.length > 0 && (
          <select
            value={tenant}
            onChange={(e) => setTenant(e.target.value)}
            className="ml-auto rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-sm"
          >
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.plan})
              </option>
            ))}
          </select>
        )}
      </div>

      {!data ? (
        <div className="text-gray-500">Loading usage…</div>
      ) : (
        <CostBody data={data} />
      )}
    </div>
  );
}

function CostBody({ data }: { data: UsageReport }) {
  return (
    <div className="space-y-6">

      <div className="grid grid-cols-3 gap-4">
        <Stat label="Total cost" value={usd(data.totals.cost_usd)} accent />
        <Stat label="Input tokens" value={num(data.totals.input_tok)} />
        <Stat label="Output tokens" value={num(data.totals.output_tok)} />
      </div>

      <section>
        <h2 className="mb-2 text-sm uppercase tracking-wide text-gray-500">By model</h2>
        <table className="w-full text-sm">
          <thead className="text-gray-500">
            <tr className="border-b border-white/10 text-left">
              <th className="py-1">Model</th><th>Calls</th><th>Input</th><th>Output</th><th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {data.by_model.map((r) => (
              <tr key={r.model} className="border-b border-white/5">
                <td className="py-1 font-mono text-cyan-300">{r.model}</td>
                <td>{num(r.calls)}</td>
                <td>{num(r.input_tok)}</td>
                <td>{num(r.output_tok)}</td>
                <td className="text-emerald-400">{usd(r.cost_usd)}</td>
              </tr>
            ))}
            {data.by_model.length === 0 && (
              <tr><td colSpan={5} className="py-2 text-gray-600">No usage yet.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section>
        <h2 className="mb-2 text-sm uppercase tracking-wide text-gray-500">By day</h2>
        <div className="space-y-1">
          {data.by_day.map((d) => (
            <div key={d.day} className="flex items-center gap-3 text-sm">
              <span className="w-28 font-mono text-gray-400">{d.day}</span>
              <span className="w-24 text-emerald-400">{usd(d.cost_usd)}</span>
              <span className="text-gray-500">{num(d.tokens)} tok</span>
            </div>
          ))}
          {data.by_day.length === 0 && <div className="text-gray-600">No usage yet.</div>}
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${accent ? "text-iris-cyan" : "text-white"}`}>
        {value}
      </div>
    </div>
  );
}
