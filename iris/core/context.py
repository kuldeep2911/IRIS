"""Context assembly — build the prompt context passed to the model.

GOLDEN RULE #3 (stateless): :class:`RequestContext` is a value created per
request and passed through the call chain — never stored at module scope.
GOLDEN RULE #5 (privacy): ``assemble`` returns a compact, SANITISED dict; raw
secrets / bodies never go in. Memory + screen context are added in later phases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid importing the gateway/event layer into the core
    from iris.core.events import EventBus


@dataclass
class RequestContext:
    """Per-request working state, threaded through the orchestrator."""

    tenant_id: str
    session_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    bus: "EventBus | None" = None
    # Confirmation behavior when no interactive channel answers (GOLDEN RULE #6).
    # Default DENY (skip) the gated action — safe by default.
    auto_confirm: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    async def emit(self, event: str, payload: Any = None) -> None:
        """Publish an orchestrator event if a bus is wired (Agent Monitor later)."""
        if self.bus is not None:
            await self.bus.publish(event, payload)


def assemble(request: str, ctx: RequestContext) -> dict[str, Any]:
    """Assemble the compact, sanitised prompt context for this request.

    For now: session id + the request text. Memory recall and screen context are
    layered in here in Phase 3 / Phase 7 — always sanitised before returning.
    """
    return {
        "session_id": ctx.session_id,
        "request": request,
        # "memory": [...],  # Phase 3
        # "screen": "...",  # Phase 7
    }


def est_tokens(assembled: dict[str, Any] | str) -> int:
    """Rough token estimate (~4 chars/token) of the assembled context."""
    text = assembled if isinstance(assembled, str) else json.dumps(assembled, default=str)
    return max(1, len(text) // 4)
