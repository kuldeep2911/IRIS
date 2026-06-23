"""MemoryStore — tenant-scoped wrapper over the agentmemory MCP tools.

GOLDEN RULE #1: the vector store is the agentmemory MCP server; this only routes
calls to it. GOLDEN RULE #4: every call is tenant-scoped (a per-tenant chroma
collection). GOLDEN RULE #8: text is redacted before storage — never persist raw
secrets.

API: ``remember`` / ``recall`` / ``forget`` (plus ``list_all`` / ``update`` used
by the Mem0 AUDN loop in 3.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

from iris.mcp.host import MCPHost
from iris.security.redaction import _redact_text

log = structlog.get_logger(__name__)


@dataclass
class Memory:
    """A recalled memory with provenance."""

    id: str
    text: str
    source: str | None = None
    confidence: float = 1.0
    distance: float | None = None
    metadata: dict[str, Any] | None = None


def _collection(tenant_id: str) -> str:
    return f"t_{tenant_id}"


class MemoryStore:
    """Routes memory ops to the agentmemory MCP server, tenant-scoped."""

    def __init__(self, mcp: MCPHost) -> None:
        self._mcp = mcp

    @property
    def available(self) -> bool:
        return self._mcp.server_for("memory_store") is not None

    async def remember(
        self,
        tenant_id: str,
        user_id: str | None,
        text: str,
        source: str | None = None,
        confidence: float = 1.0,
    ) -> str | None:
        _require_tenant(tenant_id)
        clean = _redact_text(text).strip()
        if not clean:
            return None
        metadata = {
            "tenant_id": tenant_id,
            "user_id": user_id or "",
            "source": source or "",
            "confidence": float(confidence),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        raw = await self._mcp.invoke(
            "memory_store",
            {"collection": _collection(tenant_id), "text": clean, "metadata": metadata},
        )
        return _parse(raw).get("id")

    async def recall(self, tenant_id: str, query: str, k: int = 8) -> list[Memory]:
        _require_tenant(tenant_id)
        if not query.strip():
            return []
        raw = await self._mcp.invoke(
            "memory_search",
            {"collection": _collection(tenant_id), "query": query, "n_results": k},
        )
        rows = _parse(raw, default=[])
        return [_to_memory(r) for r in rows]

    async def forget(self, tenant_id: str, memory_id: str) -> None:
        _require_tenant(tenant_id)
        await self._mcp.invoke(
            "memory_delete", {"collection": _collection(tenant_id), "id": memory_id}
        )

    async def update(
        self,
        tenant_id: str,
        memory_id: str,
        text: str | None = None,
        confidence: float | None = None,
    ) -> None:
        _require_tenant(tenant_id)
        args: dict[str, Any] = {"collection": _collection(tenant_id), "id": memory_id}
        if text is not None:
            args["text"] = _redact_text(text).strip()
        if confidence is not None:
            args["metadata"] = {"confidence": float(confidence)}
        await self._mcp.invoke("memory_update", args)

    async def list_all(self, tenant_id: str, limit: int = 200) -> list[Memory]:
        _require_tenant(tenant_id)
        raw = await self._mcp.invoke(
            "memory_list", {"collection": _collection(tenant_id), "limit": limit}
        )
        return [_to_memory(r) for r in _parse(raw, default=[])]


# ── helpers ──────────────────────────────────────────────────────────────────
def _require_tenant(tenant_id: str | None) -> None:
    if not tenant_id:
        raise ValueError("tenant_id is required (memory is tenant-scoped).")


def _parse(raw: str, default: Any = None) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def _to_memory(row: dict[str, Any]) -> Memory:
    meta = row.get("metadata") or {}
    return Memory(
        id=row.get("id", ""),
        text=row.get("text", ""),
        source=meta.get("source") or None,
        confidence=float(meta.get("confidence", 1.0)),
        distance=row.get("distance"),
        metadata=meta,
    )
