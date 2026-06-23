"""MCPHost — IRIS is an MCP CLIENT; capabilities are external servers.

GOLDEN RULE #1 (MCP-first): no tool logic is hardcoded here. The host reads
``registry.yaml``, connects to each enabled server via the MCP SDK, merges their
tool schemas (for Gemini function-calling), and routes ``invoke(tool, args)`` to
the owning server. Adding a capability = a registry entry, never core code.

Lifecycle: ``connect_all()`` at startup, ``aclose()`` at shutdown. Connections
are held open for the app's lifetime via an ``AsyncExitStack``.
"""

from __future__ import annotations

import asyncio
import shlex
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import structlog
import yaml

from iris.llm.base import ToolSchema

log = structlog.get_logger(__name__)

_DEFAULT_REGISTRY = Path(__file__).resolve().parent / "registry.yaml"
_CONNECT_TIMEOUT = 120.0  # generous: first `npx -y ...` may download the server


class ToolError(RuntimeError):
    """A normalized MCP tool failure (unknown tool, server down, tool error)."""


class MCPHost:
    """Connect to MCP servers and route tool calls. One instance per app."""

    def __init__(self, registry_path: str | Path | None = None) -> None:
        self._registry_path = Path(registry_path) if registry_path else _DEFAULT_REGISTRY
        self._stack = AsyncExitStack()
        self._sessions: dict[str, Any] = {}          # server name -> ClientSession
        self._tool_to_server: dict[str, str] = {}     # tool name  -> server name
        self._schemas: list[ToolSchema] = []          # merged, for function-calling
        self._health: dict[str, bool] = {}            # server name -> up/down
        self._connected = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def connect_all(self) -> dict[str, bool]:
        """Start/connect every enabled server. Failures are isolated, not fatal."""
        if self._connected:
            return self._health
        for name, cfg in self._load_registry().items():
            if not isinstance(cfg, dict) or not cfg.get("enabled"):
                continue
            try:
                await asyncio.wait_for(self._connect_one(name, cfg), timeout=_CONNECT_TIMEOUT)
                self._health[name] = True
                log.info("mcp.connected", server=name)
            except Exception as exc:  # noqa: BLE001 — one bad server must not sink the host
                self._health[name] = False
                log.warning("mcp.connect_failed", server=name, error=str(exc))
        self._connected = True
        return self._health

    async def aclose(self) -> None:
        """Tear down all server connections."""
        await self._stack.aclose()
        self._sessions.clear()
        self._connected = False

    # ── tool discovery / invocation ──────────────────────────────────────────
    def schemas(self) -> list[ToolSchema]:
        """Merged tool schema list for Gemini function-calling."""
        return list(self._schemas)

    def tool_names(self) -> list[str]:
        return list(self._tool_to_server.keys())

    def server_for(self, tool_name: str) -> str | None:
        return self._tool_to_server.get(tool_name)

    def health(self) -> dict[str, bool]:
        return dict(self._health)

    async def invoke(self, tool_name: str, args: dict[str, Any] | None = None) -> str:
        """Route a tool call to its owning server; return normalized text.

        Raises :class:`ToolError` on unknown tool, down server, or tool error so
        the orchestrator can ask the model for an alternative approach.
        """
        server = self._tool_to_server.get(tool_name)
        if server is None:
            raise ToolError(f"Unknown tool '{tool_name}'. Known: {self.tool_names()}")
        session = self._sessions.get(server)
        if session is None or not self._health.get(server):
            raise ToolError(f"Server '{server}' for tool '{tool_name}' is unavailable.")
        try:
            result = await session.call_tool(tool_name, args or {})
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Tool '{tool_name}' call failed: {exc}") from exc

        text = _content_to_text(getattr(result, "content", None))
        if getattr(result, "isError", False):
            raise ToolError(text or f"Tool '{tool_name}' returned an error.")
        return text

    # ── internals ────────────────────────────────────────────────────────────
    def _load_registry(self) -> dict[str, Any]:
        data = yaml.safe_load(self._registry_path.read_text(encoding="utf-8")) or {}
        return data.get("servers", {}) or {}

    async def _connect_one(self, name: str, cfg: dict[str, Any]) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        transport = cfg.get("transport", "stdio")
        if transport == "stdio":
            command, *args = shlex.split(cfg.get("command", ""))
            params = StdioServerParameters(command=command, args=args)
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif transport == "sse":
            from mcp.client.sse import sse_client

            read, write = await self._stack.enter_async_context(sse_client(cfg["url"]))
        else:
            raise ValueError(f"Unknown transport '{transport}' for server '{name}'.")

        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[name] = session

        listed = await session.list_tools()
        for tool in listed.tools:
            if tool.name in self._tool_to_server:
                log.warning(
                    "mcp.tool_name_collision",
                    tool=tool.name,
                    existing=self._tool_to_server[tool.name],
                    new=name,
                )
            self._tool_to_server[tool.name] = name
            self._schemas.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                }
            )


def _content_to_text(content: Any) -> str:
    """Flatten an MCP tool result's content blocks into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    chunks: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            chunks.append(text)
        elif getattr(block, "type", None) == "image":
            chunks.append("[image]")
        else:
            chunks.append(str(block))
    return "\n".join(chunks)
