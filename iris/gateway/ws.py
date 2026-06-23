"""WebSocket gateway — live Agent Monitor stream.

Subscribes to the in-process event bus and forwards every orchestrator /
sub-agent event (agent_start, agent_update, agent_complete, agent_failed,
tool_result, confirm_request, final) to the connected UI in real time. Nothing
is a black box.

A per-connection queue decouples the bus from the socket, so a slow client never
blocks the orchestrator's ``publish``.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

log = structlog.get_logger(__name__)

# Events surfaced to the Agent Monitor UI.
MONITOR_EVENTS: tuple[str, ...] = (
    "agent_start", "agent_update", "agent_complete", "agent_failed",
    "tool_result", "confirm_request", "final", "blocked",
)


def register_ws(app: FastAPI) -> None:
    """Mount the /ws endpoint on the app."""

    @app.websocket("/ws")
    async def agent_monitor(websocket: WebSocket) -> None:
        await websocket.accept()
        bus = websocket.app.state.event_bus
        session_filter = websocket.query_params.get("session_id")
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)

        def make_handler(event: str):
            async def handler(payload) -> None:
                data = payload if isinstance(payload, dict) else {"payload": payload}
                if session_filter and data.get("session_id") not in (None, session_filter):
                    return
                msg = {"type": event, **data}
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    pass  # drop if the client can't keep up
            return handler

        unsubs = [bus.subscribe(ev, make_handler(ev)) for ev in MONITOR_EVENTS]
        try:
            while True:
                msg = await queue.get()
                await websocket.send_json(msg)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001 — client gone / send error
            log.info("ws.closed", error=str(exc))
        finally:
            for unsub in unsubs:
                unsub()
