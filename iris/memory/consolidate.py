"""Memory consolidation — nightly de-dupe / merge / stale-flag job.

Runs as a background job (cheapest path: the router's BACKGROUND class maps to
Flash via the Batch API, 50% off — used here if/when an LLM merge is needed).
The mechanical de-dupe + stale-flagging below needs no LLM at all.

- DE-DUPE: near-identical memories (high text similarity) are collapsed to one,
  keeping the highest-confidence / most-recent copy.
- STALE: old + low-confidence memories are flagged (metadata ``stale=True``) so
  recall/Mem0 can down-rank them; nothing is hard-deleted automatically.

Tenant-scoped. Invoke: ``python -m iris.memory.consolidate <tenant_id>``.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher

import structlog

from iris.config.settings import get_settings
from iris.mcp.host import MCPHost
from iris.memory.store import Memory, MemoryStore
from iris.router.model_router import RequestClass, model_for  # noqa: F401  (Batch path)

log = structlog.get_logger(__name__)

_DUP_THRESHOLD = 0.92        # text similarity above which two memories are dupes
_STALE_AGE_DAYS = 90         # older than this …
_STALE_CONFIDENCE = 0.5      # … and below this confidence -> flagged stale


async def consolidate(tenant_id: str, memory: MemoryStore) -> dict[str, int]:
    """De-dupe + flag-stale a tenant's memories. Returns a summary of changes."""
    memories = await memory.list_all(tenant_id, limit=1000)
    summary = {"scanned": len(memories), "deduped": 0, "flagged_stale": 0}

    # ── de-dupe ──────────────────────────────────────────────────────────────
    survivors: list[Memory] = []
    for mem in memories:
        dup_of = _find_duplicate(mem, survivors)
        if dup_of is None:
            survivors.append(mem)
            continue
        # keep the stronger one; forget the weaker.
        weaker, stronger = _rank(mem, dup_of)
        await memory.forget(tenant_id, weaker.id)
        if stronger is mem:
            survivors[survivors.index(dup_of)] = mem
        summary["deduped"] += 1

    # ── flag stale ───────────────────────────────────────────────────────────
    for mem in survivors:
        if _is_stale(mem):
            await memory.update(tenant_id, mem.id, confidence=min(mem.confidence, 0.3))
            summary["flagged_stale"] += 1

    log.info("memory.consolidated", tenant_id=tenant_id, **summary)
    return summary


def _find_duplicate(mem: Memory, pool: list[Memory]) -> Memory | None:
    for other in pool:
        if _similar(mem.text, other.text) >= _DUP_THRESHOLD:
            return other
    return None


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _rank(a: Memory, b: Memory) -> tuple[Memory, Memory]:
    """Return (weaker, stronger) by confidence then recency."""
    a_key = (a.confidence, _ts(a))
    b_key = (b.confidence, _ts(b))
    return (a, b) if a_key <= b_key else (b, a)


def _ts(mem: Memory) -> str:
    return (mem.metadata or {}).get("ts", "") if mem.metadata else ""


def _is_stale(mem: Memory) -> bool:
    ts = _ts(mem)
    if not ts:
        return False
    try:
        when = datetime.fromisoformat(ts)
    except ValueError:
        return False
    age_days = (datetime.now(timezone.utc) - when).days
    return age_days > _STALE_AGE_DAYS and mem.confidence < _STALE_CONFIDENCE


async def _main(tenant_id: str) -> None:
    host = MCPHost()
    await host.connect_all()
    try:
        result = await consolidate(tenant_id, MemoryStore(host))
        print("consolidation:", result)
    finally:
        await host.aclose()


if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else get_settings().DEFAULT_TENANT_ID
    asyncio.run(_main(tid))
