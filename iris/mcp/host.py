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
import os
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
        # ── connector servers (Phase 9): per (tenant,user,connector) ───────────
        self._connector_stacks: dict[str, AsyncExitStack] = {}   # key -> stack
        self._connector_schemas: dict[str, list[ToolSchema]] = {}  # key -> schemas
        self._connector_confirm: dict[str, set[str]] = {}        # key -> confirm tools
        self._connector_token: dict[str, str] = {}               # key -> token started with

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def connect_all(self) -> dict[str, bool]:
        """Start/connect every enabled server. Failures are isolated, not fatal."""
        if self._connected:
            return self._health
        for name, cfg in self._load_registry().items():
            if not isinstance(cfg, dict) or not cfg.get("enabled"):
                continue
            # Skip (mark down) without spawning if preconditions are unmet — e.g.
            # an OAuth server with no credentials yet. Avoids hangs/downloads.
            unmet = _unmet_preconditions(cfg)
            if unmet:
                self._health[name] = False
                log.info("mcp.skipped", server=name, missing=unmet)
                continue
            timeout = float(cfg.get("connect_timeout", _CONNECT_TIMEOUT))
            try:
                await asyncio.wait_for(self._connect_one(name, cfg), timeout=timeout)
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

    # ── connector server lifecycle (Phase 9) ──────────────────────────────────
    @staticmethod
    def connector_key(tenant_id: str, user_id: str | None, connector_id: str) -> str:
        return f"conn:{tenant_id}:{user_id or '-'}:{connector_id}"

    async def start_connector_server(self, connection: Any, token: str) -> None:
        """Start a connected connector's MCP server with the token injected.

        Restarts cleanly if already running (used after a token refresh). The
        server's tools become routable immediately and appear in
        ``schemas_for_user`` for this (tenant, user).
        """
        from iris.connectors.catalog import get_connector

        spec = get_connector(connection.connector_id)
        key = self.connector_key(connection.tenant_id, connection.user_id, connection.connector_id)
        await self.stop_connector_server(
            connection.tenant_id, connection.user_id, connection.connector_id
        )

        stack = AsyncExitStack()
        session = await self._spawn_connector(stack, spec, token)
        await session.initialize()
        listed = await session.list_tools()

        schemas: list[ToolSchema] = []
        for tool in listed.tools:
            self._tool_to_server[tool.name] = key
            schemas.append({
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {"type": "object", "properties": {}},
            })
        self._sessions[key] = session
        self._connector_stacks[key] = stack
        self._connector_schemas[key] = schemas
        self._connector_confirm[key] = set(spec.confirm_tools)
        self._connector_token[key] = token
        self._health[key] = True
        log.info("connector.server_started", connector=connection.connector_id, tools=len(schemas))

    async def stop_connector_server(
        self, tenant_id: str, user_id: str | None, connector_id: str
    ) -> None:
        key = self.connector_key(tenant_id, user_id, connector_id)
        if key not in self._connector_stacks:
            return
        # remove this connector's tool routes
        for tool in [t for t, srv in self._tool_to_server.items() if srv == key]:
            self._tool_to_server.pop(tool, None)
        self._connector_schemas.pop(key, None)
        self._connector_confirm.pop(key, None)
        self._connector_token.pop(key, None)
        self._sessions.pop(key, None)
        self._health.pop(key, None)
        try:
            await self._connector_stacks.pop(key).aclose()
        except Exception as exc:  # noqa: BLE001 — teardown best-effort
            log.warning("connector.stop_failed", connector=connector_id, error=str(exc))

    def schemas_for_user(self, tenant_id: str, user_id: str | None) -> list[ToolSchema]:
        """Core tool schemas PLUS this user's connected connector tools."""
        prefix = f"conn:{tenant_id}:{user_id or '-'}:"
        out = list(self._schemas)
        for key, schemas in self._connector_schemas.items():
            if key.startswith(prefix):
                out.extend(schemas)
        return out

    def connector_confirm_tools(self, tenant_id: str, user_id: str | None) -> set[str]:
        """Union of confirm_tools across this user's connected connectors."""
        prefix = f"conn:{tenant_id}:{user_id or '-'}:"
        tools: set[str] = set()
        for key, confirm in self._connector_confirm.items():
            if key.startswith(prefix):
                tools |= confirm
        return tools

    def running_connectors(self, tenant_id: str, user_id: str | None) -> list[str]:
        prefix = f"conn:{tenant_id}:{user_id or '-'}:"
        return [k.split(":")[-1] for k in self._connector_stacks if k.startswith(prefix)]

    def connector_started_token(self, tenant_id: str, user_id: str | None, connector_id: str) -> str | None:
        return self._connector_token.get(self.connector_key(tenant_id, user_id, connector_id))

    async def _spawn_connector(self, stack: AsyncExitStack, spec: Any, token: str) -> Any:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        mcp_spec = spec.mcp
        if mcp_spec.transport == "stdio":
            command, *args = shlex.split(mcp_spec.command or "")
            env = dict(os.environ)
            if mcp_spec.token_injection == "env" and mcp_spec.token_env_var:
                env[mcp_spec.token_env_var] = token
            elif mcp_spec.token_injection == "arg":
                args.append(token)
            params = StdioServerParameters(command=command, args=args, env=env)
            read, write = await stack.enter_async_context(stdio_client(params))
        elif mcp_spec.transport == "sse":
            from mcp.client.sse import sse_client

            await _assert_reachable(mcp_spec.url)
            headers = None
            if mcp_spec.token_injection == "header":
                headers = {"Authorization": f"Bearer {token}"}
            read, write = await stack.enter_async_context(sse_client(mcp_spec.url, headers=headers))
        else:
            raise ToolError(f"unknown transport '{mcp_spec.transport}'")
        return await stack.enter_async_context(ClientSession(read, write))

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
        from iris.core.telemetry import span

        try:
            with span("mcp.invoke", tool=tool_name, server=server):
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
            url = cfg["url"]
            # Fast fail if nothing is listening (browser_use/browser_mcp may be
            # off) so we don't block on the full connect timeout.
            await _assert_reachable(url)
            from mcp.client.sse import sse_client

            read, write = await self._stack.enter_async_context(sse_client(url))
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


def _unmet_preconditions(cfg: dict[str, Any]) -> list[str]:
    """Return missing precondition names: required env vars / files not present.

    Lets a server be declared+enabled yet stay down (without spawning) until the
    user configures it — e.g. OAuth credentials for gmail/calendar.
    """
    import os
    from pathlib import Path

    missing: list[str] = []
    for env in cfg.get("requires_env", []) or []:
        if not os.environ.get(env):
            missing.append(f"env:{env}")
    for path in cfg.get("requires_file", []) or []:
        if not Path(path).expanduser().exists():
            missing.append(f"file:{path}")
    return missing


async def _assert_reachable(url: str, timeout: float = 2.0) -> None:
    """Quick TCP check so a down SSE server fails fast (not on the long timeout)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
    except Exception as exc:  # noqa: BLE001
        raise ConnectionError(f"{host}:{port} not reachable ({exc})") from exc


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
