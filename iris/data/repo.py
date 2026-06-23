"""Repositories — GOLDEN RULE #4: every method is tenant-scoped.

Each repo takes a session and EVERY data method takes ``tenant_id`` and filters
by it. A guard raises if ``tenant_id`` is missing, so an unscoped query can't be
written by accident. ``seed_defaults`` creates the default tenant + user;
``record_usage`` is the GeminiClient usage sink that writes a usage row.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iris.config.settings import get_settings
from iris.data.db import current_tenant_id, session_scope
from iris.data.models import (
    ActionAudit,
    Connection,
    Memory,
    Message,
    Session,
    Tenant,
    Usage,
    User,
)
from iris.llm.base import Usage as UsageTokens
from iris.router.model_router import cost_usd

DEFAULT_USER_NAME = "owner"


class TenantScopeError(ValueError):
    """Raised when a tenant-scoped method is called without a tenant_id."""


def _require_tenant(tenant_id: str | None) -> None:
    if not tenant_id:
        raise TenantScopeError("tenant_id is required: every query must be tenant-scoped.")


class _BaseRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class TenantRepo(_BaseRepo):
    async def get(self, tenant_id: str) -> Tenant | None:
        _require_tenant(tenant_id)
        return await self.session.get(Tenant, tenant_id)

    async def ensure(self, tenant_id: str, name: str = "local", plan: str = "free") -> Tenant:
        _require_tenant(tenant_id)
        existing = await self.session.get(Tenant, tenant_id)
        if existing:
            return existing
        tenant = Tenant(id=tenant_id, name=name, plan=plan)
        self.session.add(tenant)
        await self.session.flush()
        return tenant


class UserRepo(_BaseRepo):
    async def get_or_create_default(self, tenant_id: str) -> User:
        _require_tenant(tenant_id)
        q = select(User).where(User.tenant_id == tenant_id).limit(1)
        user = (await self.session.execute(q)).scalar_one_or_none()
        if user:
            return user
        user = User(tenant_id=tenant_id, name=DEFAULT_USER_NAME)
        self.session.add(user)
        await self.session.flush()
        return user


class SessionRepo(_BaseRepo):
    async def get_or_create(
        self, tenant_id: str, session_id: str | None, user_id: str | None
    ) -> Session:
        _require_tenant(tenant_id)
        if session_id:
            existing = await self.session.get(Session, session_id)
            if existing and existing.tenant_id == tenant_id:
                return existing
            sess = Session(id=session_id, tenant_id=tenant_id, user_id=user_id)
        else:
            sess = Session(tenant_id=tenant_id, user_id=user_id)
        self.session.add(sess)
        await self.session.flush()
        return sess


class MessageRepo(_BaseRepo):
    async def add(
        self,
        tenant_id: str,
        session_id: str,
        role: str,
        content: str,
        model: str | None = None,
        input_tok: int = 0,
        output_tok: int = 0,
    ) -> Message:
        _require_tenant(tenant_id)
        msg = Message(
            tenant_id=tenant_id,
            session_id=session_id,
            role=role,
            content=content,
            model=model,
            input_tok=input_tok,
            output_tok=output_tok,
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def list_for_session(self, tenant_id: str, session_id: str) -> list[Message]:
        _require_tenant(tenant_id)
        q = (
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.session_id == session_id)
            .order_by(Message.created_at)
        )
        return list((await self.session.execute(q)).scalars().all())


class MemoryRepo(_BaseRepo):
    async def add(
        self,
        tenant_id: str,
        text: str,
        user_id: str | None = None,
        source: str | None = None,
        confidence: float = 1.0,
        embedding_ref: str | None = None,
    ) -> Memory:
        _require_tenant(tenant_id)
        mem = Memory(
            tenant_id=tenant_id,
            user_id=user_id,
            text=text,
            source=source,
            confidence=confidence,
            embedding_ref=embedding_ref,
        )
        self.session.add(mem)
        await self.session.flush()
        return mem

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[Memory]:
        _require_tenant(tenant_id)
        q = (
            select(Memory)
            .where(Memory.tenant_id == tenant_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(q)).scalars().all())


class ConnectionRepo(_BaseRepo):
    async def upsert(
        self, tenant_id: str, type_: str, status: str, credentials_ref: str | None = None
    ) -> Connection:
        _require_tenant(tenant_id)
        q = select(Connection).where(
            Connection.tenant_id == tenant_id, Connection.type == type_
        )
        conn = (await self.session.execute(q)).scalar_one_or_none()
        if conn:
            conn.status = status
            conn.credentials_ref = credentials_ref
        else:
            conn = Connection(
                tenant_id=tenant_id, type=type_, status=status, credentials_ref=credentials_ref
            )
            self.session.add(conn)
        await self.session.flush()
        return conn


class AuditRepo(_BaseRepo):
    async def add(
        self,
        tenant_id: str,
        action: str,
        user_id: str | None = None,
        params_hash: str | None = None,
        result: str | None = None,
    ) -> ActionAudit:
        _require_tenant(tenant_id)
        row = ActionAudit(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            params_hash=params_hash,
            result=result,
        )
        self.session.add(row)
        await self.session.flush()
        return row


class UsageRepo(_BaseRepo):
    async def add(
        self,
        tenant_id: str,
        model: str,
        input_tok: int,
        output_tok: int,
        cost_usd: float = 0.0,
    ) -> Usage:
        _require_tenant(tenant_id)
        row = Usage(
            tenant_id=tenant_id,
            model=model,
            input_tok=input_tok,
            output_tok=output_tok,
            cost_usd=cost_usd,
        )
        self.session.add(row)
        await self.session.flush()
        return row


# ── startup helpers ──────────────────────────────────────────────────────────
async def seed_defaults() -> tuple[str, str]:
    """Ensure the default tenant + user exist. Returns (tenant_id, user_id)."""
    tenant_id = get_settings().DEFAULT_TENANT_ID
    async with session_scope() as s:
        await TenantRepo(s).ensure(tenant_id, name=tenant_id)
        user = await UserRepo(s).get_or_create_default(tenant_id)
        return tenant_id, user.id


# ── GeminiClient usage sink (GOLDEN RULE: cost metering per call) ─────────────
async def record_usage(model: str, usage: UsageTokens) -> None:
    """Write a usage row for one LLM call; attributes cost to the current tenant.

    Wired as ``get_llm(usage_sink=record_usage)``. Failures here never break a
    reply (the LLM client catches sink errors).
    """
    tenant_id = current_tenant_id.get() or get_settings().DEFAULT_TENANT_ID
    async with session_scope() as s:
        await UsageRepo(s).add(
            tenant_id=tenant_id,
            model=model,
            input_tok=usage.input_tok,
            output_tok=usage.output_tok,
            cost_usd=cost_usd(model, usage.input_tok, usage.output_tok),
        )
