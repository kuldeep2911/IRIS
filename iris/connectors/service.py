"""ConnectorService — the single entry point for the API + orchestrator.

All methods are tenant + user scoped. Ties together the catalog, OAuth engine,
PAT path, token vault, the connections repo, and (Phase 9.5) the dynamic MCP
server lifecycle. Construct one per request with the caller's tenant/user.
"""

from __future__ import annotations

from typing import Any

import structlog

from iris.connectors.catalog import get_catalog, get_connector
from iris.connectors.oauth import OAuthEngine, ReconnectRequired
from iris.connectors.repo import ConnectionRepo
from iris.connectors.token_auth import connect_with_token
from iris.connectors.token_vault import TokenVault
from iris.data.db import session_scope

log = structlog.get_logger(__name__)


class ConnectorService:
    def __init__(
        self,
        tenant_id: str,
        user_id: str | None = None,
        mcp: Any | None = None,
        vault: TokenVault | None = None,
        oauth: OAuthEngine | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._mcp = mcp
        self._vault = vault or TokenVault()
        self._oauth = oauth or OAuthEngine(self._vault)

    # ── discovery ─────────────────────────────────────────────────────────────
    async def list_available(self) -> list[dict]:
        async with session_scope() as s:
            conns = {
                c.connector_id: c
                for c in await ConnectionRepo(s).list_connections(self._tenant_id, self._user_id)
            }
        out: list[dict] = []
        for spec in get_catalog():
            c = conns.get(spec.id)
            out.append({
                "id": spec.id,
                "name": spec.name,
                "category": spec.category,
                "icon": spec.icon,
                "auth_type": spec.auth.type,
                "help_url": spec.auth.help_url,
                "token_label": spec.auth.token_label,
                "status": c.status if c else "disconnected",
                "account_label": c.account_label if c else None,
                "last_error": c.last_error if c else None,
                "confirm_tools": spec.confirm_tools,
            })
        return out

    # ── connect flows ─────────────────────────────────────────────────────────
    async def begin_oauth(self, connector_id: str) -> str:
        spec = get_connector(connector_id)
        url, _ = self._oauth.build_authorize_url(spec, self._tenant_id, self._user_id)
        async with session_scope() as s:
            await ConnectionRepo(s).upsert_connection(
                self._tenant_id, self._user_id, connector_id, status="pending"
            )
        return url

    async def complete_oauth(self, code: str, state: str):
        conn = await self._oauth.handle_callback(code, state)
        await self._maybe_start_server(conn)
        return conn

    async def connect_token(self, connector_id: str, raw_token: str):
        spec = get_connector(connector_id)
        conn = await connect_with_token(
            spec, self._tenant_id, self._user_id, raw_token, vault=self._vault
        )
        await self._maybe_start_server(conn)
        return conn

    async def disconnect(self, connector_id: str) -> None:
        async with session_scope() as s:
            repo = ConnectionRepo(s)
            conn = await repo.get_connection(self._tenant_id, self._user_id, connector_id)
            if conn and conn.credentials_ref:
                self._vault.delete_tokens(conn.credentials_ref)
            await repo.set_status(self._tenant_id, self._user_id, connector_id, "disconnected")
        if self._mcp is not None and hasattr(self._mcp, "stop_connector_server"):
            await self._mcp.stop_connector_server(self._tenant_id, self._user_id, connector_id)

    # ── runtime ───────────────────────────────────────────────────────────────
    async def get_active_connections(self) -> list:
        async with session_scope() as s:
            conns = await ConnectionRepo(s).list_connected(self._tenant_id, self._user_id)
            for c in conns:
                s.expunge(c)
            return conns

    async def token_for(self, connector_id: str) -> str:
        spec = get_connector(connector_id)
        async with session_scope() as s:
            conn = await ConnectionRepo(s).get_connection(
                self._tenant_id, self._user_id, connector_id
            )
            if conn is None or not conn.credentials_ref:
                raise ReconnectRequired(f"{connector_id}: not connected")
            s.expunge(conn)
        if spec.auth.type == "oauth2":
            return await self._oauth.get_valid_access_token(conn)
        # pat / api_key: the stored token IS the credential (no refresh)
        return self._vault.get_tokens(conn.credentials_ref).access_token

    async def ensure_fresh(self, connector_id: str) -> str:
        """Guarantee a running connector server has a VALID token before use.

        Refreshes an expired OAuth token (via the vault) and, if the token
        changed, restarts the server with the new token (servers read the token
        at startup). Raises ReconnectRequired if the connection is gone/revoked.
        """
        async with session_scope() as s:
            conn = await ConnectionRepo(s).get_connection(
                self._tenant_id, self._user_id, connector_id
            )
            if conn is None or not conn.credentials_ref:
                raise ReconnectRequired(f"{connector_id}: not connected")
            s.expunge(conn)
        token = await self.token_for(connector_id)
        if self._mcp is not None and hasattr(self._mcp, "connector_started_token"):
            started = self._mcp.connector_started_token(
                self._tenant_id, self._user_id, connector_id
            )
            if started is not None and started != token:
                await self._mcp.start_connector_server(conn, token)  # restart w/ fresh token
        return token

    async def status(self, connector_id: str) -> dict:
        async with session_scope() as s:
            conn = await ConnectionRepo(s).get_connection(
                self._tenant_id, self._user_id, connector_id
            )
        return {
            "connector_id": connector_id,
            "status": conn.status if conn else "disconnected",
            "account_label": conn.account_label if conn else None,
            "last_error": conn.last_error if conn else None,
        }

    # ── internal ──────────────────────────────────────────────────────────────
    async def _maybe_start_server(self, conn) -> None:
        if self._mcp is None or not hasattr(self._mcp, "start_connector_server"):
            return
        try:
            token = await self.token_for(conn.connector_id)
            await self._mcp.start_connector_server(conn, token)
        except Exception as exc:  # noqa: BLE001 — connect succeeded; server start is best-effort
            log.warning("connector.server_start_failed", connector=conn.connector_id, error=str(exc))
