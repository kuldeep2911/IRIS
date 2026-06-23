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
    # MemoryStore for recall during context assembly (set by the orchestrator).
    # Typed as Any to keep the core import-light. Duck-typed: .recall(...).
    memory: Any = None
    # ScreenIntel (Phase 7.2), set by the orchestrator when enabled. Duck-typed.
    screen: Any = None
    # Confirmation behavior when no interactive channel answers (GOLDEN RULE #6).
    # Default DENY (skip) the gated action — safe by default.
    auto_confirm: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    async def emit(self, event: str, payload: Any = None) -> None:
        """Publish an orchestrator event if a bus is wired (Agent Monitor later)."""
        if self.bus is not None:
            await self.bus.publish(event, payload)


async def assemble(request: str, ctx: RequestContext) -> dict[str, Any]:
    """Assemble the compact, sanitised prompt context for this request.

    Includes a de-duplicated, sanitised block of recalled user memories when a
    memory store is wired (GOLDEN RULE #5: only sanitised context to Gemini).
    Screen context is layered in here in Phase 7.
    """
    memory_block = await _recall_memory(request, ctx)
    return {
        "session_id": ctx.session_id,
        "request": request,
        "memory": memory_block,  # list[str], already sanitised + deduped
        "screen": await _screen_context(request, ctx),  # str | None (opt-in, in-memory)
    }


# Lightweight signal that the user is asking about their current screen/work.
_SCREEN_QUERY_HINTS = (
    "what am i working on", "what's on my screen", "whats on my screen",
    "this screen", "on screen", "what do you see", "looking at", "right now",
    "current window", "what am i doing",
)


async def _screen_context(request: str, ctx: RequestContext) -> str | None:
    """Opt-in screen description, only when enabled and the ask is screen-related.

    Best-effort and in-memory only (GOLDEN RULE #5: nothing sensitive persisted).
    """
    if ctx.screen is None or not getattr(ctx.screen, "enabled", False):
        return None
    t = (request or "").lower()
    if not any(h in t for h in _SCREEN_QUERY_HINTS):
        return getattr(ctx.screen, "recent", lambda _t: None)(ctx.tenant_id)
    try:
        return await ctx.screen.describe(ctx.tenant_id, refresh=True)
    except Exception:  # noqa: BLE001
        return None


async def _recall_memory(request: str, ctx: RequestContext, k: int = 8) -> list[str]:
    """Recall relevant memories, dedupe, and return compact lines.

    Best-effort: memory failures never break a request.
    """
    if ctx.memory is None or not getattr(ctx.memory, "available", True):
        return []
    try:
        memories = await ctx.memory.recall(ctx.tenant_id, request, k=k)
    except Exception as exc:  # noqa: BLE001
        from structlog import get_logger

        get_logger(__name__).warning("context.recall_failed", error=str(exc))
        return []

    seen: set[str] = set()
    lines: list[str] = []
    for mem in memories:
        text = (getattr(mem, "text", "") or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            lines.append(text)
    return lines


def est_tokens(assembled: dict[str, Any] | str) -> int:
    """Rough token estimate (~4 chars/token) of the assembled context."""
    text = assembled if isinstance(assembled, str) else json.dumps(assembled, default=str)
    return max(1, len(text) // 4)


# ── data sanitiser (GOLDEN RULE #5) ──────────────────────────────────────────
# Final safety net before any payload reaches Gemini: redact secrets and strip
# raw email/chat/file bodies. Tool results are already summarised at the
# orchestrator boundary; this guarantees the invariant for the WHOLE payload.
def sanitise_outbound(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with every text content sanitised."""
    from iris.security.redaction import _redact_text

    out: list[dict[str, Any]] = []
    for msg in messages:
        clean = dict(msg)
        content = clean.get("content")
        if isinstance(content, str):
            clean["content"] = _redact_text(content)
        out.append(clean)
    return out


def contains_raw_body(text: str) -> bool:
    """Heuristic used by the privacy audit: does text look like a raw body dump?"""
    from iris.core.privacy import _BODY_KEYS

    low = (text or "").lower()
    # Raw bodies carry these JSON keys verbatim; summaries drop them.
    return any(f'"{k}"' in low for k in _BODY_KEYS)
