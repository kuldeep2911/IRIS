"""Async SQLAlchemy engine + session factory (from DATABASE_URL).

The engine / sessionmaker are long-lived infrastructure singletons (like a
connection pool) — NOT per-request state, so this respects the stateless-core
rule. Sync-style URLs from settings are normalized to async drivers here.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from iris.config.settings import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# Current tenant for the in-flight request (set by the gateway middleware).
# Lets the usage sink attribute cost to the right tenant without threading it
# through the LLM client. Defaults to None -> caller falls back to default.
current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _async_url(url: str) -> str:
    """Map a sync DB URL to its async driver."""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql+asyncpg://") or url.startswith("sqlite+aiosqlite://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        url = _async_url(get_settings().DATABASE_URL)
        _engine = create_async_engine(url, future=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def session_scope():
    """Transactional session scope: commit on success, rollback on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    """Create all tables (simple create_all; Alembic can replace this later)."""
    import iris.data.models  # noqa: F401  — register tables on Base.metadata

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
