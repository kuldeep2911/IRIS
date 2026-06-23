"""Smoke test: connect MCP servers, list tools, do a filesystem round-trip.

Proves the MCP-first backbone works: connect_all() -> discover tools -> write a
file then read it back through the filesystem MCP server, all inside ./workspace.

Run: ``python scripts/smoke_mcp.py``
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from iris.mcp.host import MCPHost  # noqa: E402

WORKSPACE = ROOT / "workspace"


def _pick(tool_names: list[str], *must_contain: str) -> str | None:
    for name in tool_names:
        low = name.lower()
        if all(token in low for token in must_contain):
            return name
    return None


async def main() -> None:
    host = MCPHost()
    health = await host.connect_all()
    print("server health:", health)

    tools = host.tool_names()
    print(f"\ndiscovered {len(tools)} tools:")
    for name in tools:
        print(f"  - {name}  (server: {host.server_for(name)})")

    # find a write + read tool from the filesystem server
    write_tool = _pick(tools, "write", "file")
    read_tool = _pick(tools, "read", "text") or _pick(tools, "read", "file")
    if not write_tool or not read_tool:
        print("\nFAIL: filesystem write/read tools not discovered.")
        await host.aclose()
        sys.exit(1)

    target = WORKSPACE / "mcp_smoke.txt"
    payload = "IRIS MCP round-trip ok"

    print(f"\nwrite via '{write_tool}' -> {target.name}")
    await host.invoke(write_tool, {"path": str(target), "content": payload})

    print(f"read via '{read_tool}' <- {target.name}")
    read_back = await host.invoke(read_tool, {"path": str(target)})
    print("read content:", read_back.strip())

    assert payload in read_back, "round-trip mismatch!"
    print("\nfilesystem round-trip: OK")

    await host.aclose()


if __name__ == "__main__":
    asyncio.run(main())
