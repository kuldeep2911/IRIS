"""Smoke test: the multi-agent commander chain (Phase 6.1).

Runs the acceptance task through the orchestrator and prints the live agent
chain (commander -> specialists -> tool calls -> review -> final), collected off
the event bus. Proves planning + delegation + review run end to end.

Run: ``python scripts/smoke_agents.py``
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from iris.core.context import RequestContext  # noqa: E402
from iris.core.events import EventBus  # noqa: E402
from iris.core.orchestrator import Orchestrator  # noqa: E402
from iris.core.planner import is_multipart, should_delegate  # noqa: E402
from iris.llm import get_llm  # noqa: E402
from iris.mcp.host import MCPHost  # noqa: E402
from iris.router.model_router import RequestClass, classify  # noqa: E402

TASK = "Build a small React landing page and deploy it to a static host."


async def main() -> None:
    rc = classify(TASK)
    print(f"classify={rc.name}  multipart={is_multipart(TASK)}  "
          f"delegate={should_delegate(rc, TASK)}\n")
    assert should_delegate(rc, TASK), "task should route to the multi-agent path"

    host = MCPHost()
    await host.connect_all()
    orch = Orchestrator(llm=get_llm(), mcp=host)

    bus = EventBus()
    chain: list[str] = []
    for ev in ("agent_start", "agent_update", "agent_complete", "agent_failed",
               "tool_result", "confirm_request", "final"):
        async def _h(payload, _ev=ev):
            who = (payload or {}).get("agent_name", "")
            summ = (payload or {}).get("summary", "") or (payload or {}).get("text", "")[:60]
            chain.append(f"{_ev:14} {who:12} {summ}")
        bus.subscribe(ev, _h)

    ctx = RequestContext(tenant_id="agents_smoke", session_id="s1", bus=bus, auto_confirm=False)
    try:
        result = await orch.handle(TASK, ctx)
        await asyncio.sleep(0.1)  # let fire-and-forget learn settle

        print("--- agent chain ---")
        for line in chain:
            print(" ", line)
        print("-------------------")
        print("\nFINAL:", result.text[:400])
        print(f"\nmodel={result.model} steps={result.steps} tokens={result.usage.total_tok}")

        starts = [c for c in chain if c.startswith("agent_start")]
        assert any("commander" in c for c in starts), "commander did not start"
        assert len(starts) >= 2, "no specialist sub-agent ran"
        assert any(c.startswith("final") for c in chain), "no final answer emitted"
        print("\nmulti-agent chain: OK")
    finally:
        await host.aclose()


if __name__ == "__main__":
    asyncio.run(main())
