"""ORM models — GOLDEN RULE #4: every table carries ``tenant_id``.

Single-user runs use the default tenant ('local'); the schema is already
multi-tenant so scaling to SaaS is additive, not a rewrite. Repositories
(``repo.py``) enforce that every query is tenant-scoped.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from iris.data.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    plan: Mapped[str] = mapped_column(String(64), default="free")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    auth_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=_now)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tok: Mapped[int] = mapped_column(Integer, default=0)
    output_tok: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    embedding_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), default="disconnected")
    credentials_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ActionAudit(Base):
    __tablename__ = "actions_audit"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(255))
    params_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(default=_now)


class Usage(Base):
    __tablename__ = "usage"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64))
    input_tok: Mapped[int] = mapped_column(Integer, default=0)
    output_tok: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ts: Mapped[datetime] = mapped_column(default=_now)


# Composite indexes for the common tenant-scoped lookups.
Index("ix_messages_tenant_session", Message.tenant_id, Message.session_id)
Index("ix_usage_tenant_ts", Usage.tenant_id, Usage.ts)
