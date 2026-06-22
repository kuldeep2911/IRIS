"""Async in-process event bus — components talk via events, never direct calls.

GOLDEN RULE #3 (stateless core): the bus holds only its subscription wiring, not
request/session state. Payloads flow through; nothing per-request is retained.

This is the simple in-process pub/sub used now (orchestrator/sub-agent events,
Agent Monitor later). A networked bus (Redis pub/sub) can replace it behind the
same ``subscribe`` / ``publish`` API without touching publishers or subscribers.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# An async subscriber: receives the published payload.
AsyncCallback = Callable[[Any], Awaitable[None]]


class EventBus:
    """Minimal async pub/sub. One instance per app, injected where needed."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[AsyncCallback]] = defaultdict(list)

    def subscribe(self, event: str, callback: AsyncCallback) -> Callable[[], None]:
        """Register an async callback for ``event``. Returns an unsubscribe fn."""
        self._subscribers[event].append(callback)

        def _unsubscribe() -> None:
            try:
                self._subscribers[event].remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    async def publish(self, event: str, payload: Any = None) -> None:
        """Invoke all subscribers for ``event`` concurrently.

        A failing subscriber is logged but never breaks the publisher or the
        other subscribers (events are best-effort, not part of the request path).
        """
        callbacks = list(self._subscribers.get(event, ()))
        if not callbacks:
            return
        results = await asyncio.gather(
            *(cb(payload) for cb in callbacks), return_exceptions=True
        )
        for cb, result in zip(callbacks, results):
            if isinstance(result, Exception):
                log.warning(
                    "eventbus.subscriber_failed",
                    event=event,
                    callback=getattr(cb, "__qualname__", repr(cb)),
                    error=str(result),
                )

    def publish_soon(self, event: str, payload: Any = None) -> "asyncio.Task[None]":
        """Fire-and-forget publish (e.g. memory.learn at the end of a turn)."""
        return asyncio.create_task(self.publish(event, payload))
