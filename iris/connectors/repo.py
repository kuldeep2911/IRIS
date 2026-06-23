"""ConnectionRepo — tenant + user scoped persistence for connector connections.

Every method takes ``tenant_id`` (and ``user_id``) and filters by it. Stores only
a ``credentials_ref`` (keychain key), never the token itself.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iris.data.models import Connection


class ConnectionScopeError(ValueError):
    """Raised when a connector query is missing its tenant scope."""


def _require_tenant(tenant_id: str | None) -> None:
    if not tenant_id:
        raise ConnectionScopeError("tenant_id is required (connections are tenant-scoped).")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConnectionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_connection(
        self, tenant_id: str, user_id: str | None, connector_id: str
    ) -> Connection | None:
        _require_tenant(tenant_id)
        q = select(Connection).where(
            Connection.tenant_id == tenant_id,
            Connection.user_id == user_id,
            Connection.connector_id == connector_id,
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def list_connections(self, tenant_id: str, user_id: str | None) -> list[Connection]:
        _require_tenant(tenant_id)
        q = select(Connection).where(
            Connection.tenant_id == tenant_id,
            Connection.user_id == user_id,
        )
        return list((await self.session.execute(q)).scalars().all())

    async def list_connected(self, tenant_id: str, user_id: str | None) -> list[Connection]:
        _require_tenant(tenant_id)
        q = select(Connection).where(
            Connection.tenant_id == tenant_id,
            Connection.user_id == user_id,
            Connection.status == "connected",
        )
        return list((await self.session.execute(q)).scalars().all())

    async def upsert_connection(
        self,
        tenant_id: str,
        user_id: str | None,
        connector_id: str,
        *,
        status: str = "pending",
        scopes_granted: str | None = None,
        account_label: str | None = None,
        credentials_ref: str | None = None,
    ) -> Connection:
        _require_tenant(tenant_id)
        conn = await self.get_connection(tenant_id, user_id, connector_id)
        if conn is None:
            conn = Connection(
                tenant_id=tenant_id, user_id=user_id, connector_id=connector_id,
                type=connector_id,
            )
            self.session.add(conn)
        conn.status = status
        if scopes_granted is not None:
            conn.scopes_granted = scopes_granted
        if account_label is not None:
            conn.account_label = account_label
        if credentials_ref is not None:
            conn.credentials_ref = credentials_ref
        conn.last_error = None
        conn.updated_at = _now()
        await self.session.flush()
        return conn

    async def set_status(
        self, tenant_id: str, user_id: str | None, connector_id: str, status: str
    ) -> None:
        _require_tenant(tenant_id)
        conn = await self.get_connection(tenant_id, user_id, connector_id)
        if conn:
            conn.status = status
            conn.updated_at = _now()
            await self.session.flush()

    async def set_error(
        self, tenant_id: str, user_id: str | None, connector_id: str, error: str
    ) -> None:
        _require_tenant(tenant_id)
        conn = await self.get_connection(tenant_id, user_id, connector_id)
        if conn:
            conn.status = "error"
            conn.last_error = error[:1000]
            conn.updated_at = _now()
            await self.session.flush()

    async def mark_used(
        self, tenant_id: str, user_id: str | None, connector_id: str
    ) -> None:
        _require_tenant(tenant_id)
        conn = await self.get_connection(tenant_id, user_id, connector_id)
        if conn:
            conn.last_used_at = _now()
            await self.session.flush()

    async def delete_connection(
        self, tenant_id: str, user_id: str | None, connector_id: str
    ) -> None:
        _require_tenant(tenant_id)
        conn = await self.get_connection(tenant_id, user_id, connector_id)
        if conn:
            await self.session.delete(conn)
            await self.session.flush()
