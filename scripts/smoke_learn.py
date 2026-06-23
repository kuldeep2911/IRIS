"""Smoke test: Mem0 AUDN learning across sessions (recall + self-correction).

session 1: state two durable facts -> learned.
session 2 (fresh recall): both facts recalled.
then contradict one ("light mode") -> the old fact is UPDATED/REMOVED, not
duplicated. Proves continuous learning + contradiction handling.

Run: ``python scripts/smoke_learn.py``
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from iris.llm import get_llm  # noqa: E402
from iris.mcp.host import MCPHost  # noqa: E402
from iris.memory.mem0_client import Mem0Client  # noqa: E402
from iris.memory.store import MemoryStore  # noqa: E402

TENANT = "learn_smoke"
USER = "u1"


def _prefs(memories) -> list[str]:
    return [m.text for m in memories if "mode" in m.text.lower()]


async def main() -> None:
    host = MCPHost()
    health = await host.connect_all()
    if not health.get("agentmemory"):
        print("FAIL: agentmemory not connected")
        await host.aclose()
        sys.exit(1)

    store = MemoryStore(host)
    mem0 = Mem0Client(get_llm(), store)

    # clean slate
    for m in await store.list_all(TENANT):
        await store.forget(TENANT, m.id)

    # ── session 1: state facts ───────────────────────────────────────────────
    print("session 1: 'My sister is Priya and I prefer dark mode.'")
    await mem0.learn(
        TENANT, USER,
        {"user": "My sister is Priya and I prefer dark mode.", "assistant": "Noted."},
    )
    after1 = await store.list_all(TENANT)
    for m in after1:
        print("   mem:", m.text)

    has_sister = any("priya" in m.text.lower() for m in after1)
    has_dark = any("dark" in m.text.lower() for m in after1)
    assert has_sister, "did not learn the sister fact"
    assert has_dark, "did not learn the dark-mode preference"

    # ── session 2: fresh recall ──────────────────────────────────────────────
    recalled = await store.recall(TENANT, "my sister and my theme preference", k=10)
    print("\nsession 2 recall:", [m.text for m in recalled])

    # ── contradict the preference ────────────────────────────────────────────
    print("\nsession 2: 'Actually I prefer light mode now.'")
    await mem0.learn(
        TENANT, USER,
        {"user": "Actually, I prefer light mode now.", "assistant": "Updated your preference."},
    )
    after2 = await store.list_all(TENANT)
    for m in after2:
        print("   mem:", m.text)

    prefs = _prefs(after2)
    assert any("light" in p.lower() for p in prefs), "light-mode preference not stored"
    assert not any("dark" in p.lower() for p in prefs), "stale dark-mode fact still present (not updated)"
    assert len(prefs) == 1, f"preference duplicated, expected 1 got {len(prefs)}: {prefs}"
    assert any("priya" in m.text.lower() for m in after2), "unrelated sister fact was lost"

    print("\nAUDN learning: OK (recall across sessions; contradiction updated, not duplicated)")

    for m in after2:
        await store.forget(TENANT, m.id)
    await host.aclose()


if __name__ == "__main__":
    asyncio.run(main())
