// IRIS dashboard shell — scaffold only. Pages (Chat, Agent Monitor, Memory,
// Connections, Settings), WebSocket streaming, and the optional avatar are
// built out in PHASE 5.2 / 6.2.
export default function App() {
  return (
    <div className="min-h-screen bg-iris-bg text-gray-200 flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">
          I.R.I.S.{" "}
          <span className="text-iris-cyan">v5</span>
        </h1>
        <p className="mt-2 text-gray-400">Dashboard scaffold — built out in Phase 5.</p>
      </div>
    </div>
  );
}
