"""Smoke test: Agent Monitor WebSocket stream (Phase 6.2).

Connects to /ws, fires a tool-using /chat request, and asserts that live events
(tool_result / final) arrive over the socket. Requires the server running.

Run: ``python scripts/smoke_ws.py``
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import websockets

WS = "ws://localhost:8000/ws"
CHAT = "http://localhost:8000/chat"


async def main() -> None:
    received: list[dict] = []
    async with websockets.connect(WS) as sock:
        async def reader() -> None:
            async for raw in sock:
                received.append(json.loads(raw))

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.5)

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(CHAT, json={
                "message": "Fetch https://example.com and save its title to ws_demo.txt"
            })
            r.raise_for_status()

        await asyncio.sleep(1.0)
        task.cancel()

    types = [e.get("type") for e in received]
    print("events received over WS:", types)
    assert received, "no events streamed over the WebSocket"
    assert "final" in types, "no 'final' event streamed"
    print("Agent Monitor WS stream: OK")


if __name__ == "__main__":
    asyncio.run(main())
