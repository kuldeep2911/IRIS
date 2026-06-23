// IRIS dashboard — routes + layout. Dark theme; WebSocket connects on mount.
import { useEffect } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Chat from "./pages/Chat";
import AgentMonitor from "./pages/AgentMonitor";
import Memory from "./pages/Memory";
import Connections from "./pages/Connections";
import Settings from "./pages/Settings";
import { connectWs } from "./api/ws";

export default function App() {
  useEffect(() => {
    connectWs();
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Chat />} />
          <Route path="agents" element={<AgentMonitor />} />
          <Route path="memory" element={<Memory />} />
          <Route path="connections" element={<Connections />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
