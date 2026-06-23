"""Smoke test: persistent semantic memory via the agentmemory MCP server.

Stores 3 facts, recalls by a related query, and asserts the relevant fact ranks
first. Proves the MCP-first memory backbone works end to end.

Run: ``python scripts/smoke_memory.py``
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from iris.mcp.host import MCPHost  # noqa: E402
from iris.memory.store import MemoryStore  # noqa: E402

TENANT = "smoke_tenant"
USER = "smoke_user"


async def main() -> None:
    host = MCPHost()
    health = await host.connect_all()
    print("server health:", health)
    if not health.get("agentmemory"):
        print("FAIL: agentmemory server not connected")
        await host.aclose()
        sys.exit(1)

    store = MemoryStore(host)

    facts = [
        "The user prefers dark mode in all applications.",
        "The user's sister is named Priya.",
        "The user works as a software engineer in Bangalore.",
    ]
    print("\nremembering 3 facts...")
    for f in facts:
        mid = await store.remember(TENANT, USER, f, source="smoke", confidence=0.9)
        print(f"  stored {mid[:8]}: {f}")

    query = "what theme or appearance does the user like?"
    print(f"\nrecall query: {query!r}")
    hits = await store.recall(TENANT, query, k=3)
    for h in hits:
        print(f"  - dist={h.distance:.3f}  {h.text}")

    assert hits, "no memories recalled"
    assert "dark mode" in hits[0].text.lower(), "most relevant fact did not rank first"
    print("\nsemantic recall: OK (dark-mode fact ranked first)")

    # cleanup
    for h in await store.list_all(TENANT):
        await store.forget(TENANT, h.id)
    await host.aclose()


if __name__ == "__main__":
    asyncio.run(main())
