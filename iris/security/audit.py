"""Audit — persist agent/tool events to actions_audit (immutable trail).

Wired to the event bus at startup: every monitored orchestrator / sub-agent
event becomes an ``actions_audit`` row (tenant-scoped), so there is a durable
record of every tool call and agent step. Best-effort: audit failures never
break a request.
"""

from __future__ import annotations

import hashlib
import json

import structlog

from iris.config.settings import get_settings
from iris.data.db import session_scope
from iris.data.repo import AuditRepo

log = structlog.get_logger(__name__)

# Events worth persisting (the agent chain + tool calls + confirmations).
AUDIT_EVENTS: tuple[str, ...] = (
    "agent_start", "agent_complete", "agent_failed",
    "tool_result", "confirm_request", "blocked",
)


async def persist_event(payload: dict | None, event: str = "event") -> None:
    """Write one event as an actions_audit row."""
    data = payload if isinstance(payload, dict) else {}
    tenant_id = data.get("tenant_id") or get_settings().DEFAULT_TENANT_ID
    action = data.get("type") or event
    summary = data.get("summary") or data.get("tool") or ""
    params_hash = hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode()).hexdigest()[:32]
    try:
        async with session_scope() as s:
            await AuditRepo(s).add(
                tenant_id=tenant_id,
                action=f"{action}:{data.get('agent_name', '')}".rstrip(":"),
                params_hash=params_hash,
                result=str(summary)[:500],
            )
    except Exception as exc:  # noqa: BLE001 — auditing must never break the flow
        log.warning("audit.persist_failed", error=str(exc))


def subscribe_audit(bus) -> None:
    """Subscribe the audit writer to the agent/tool events on the bus.

    Binds the event name so the audit ``action`` is correct even when the
    payload doesn't carry an explicit ``type``.
    """
    for event in AUDIT_EVENTS:
        async def handler(payload, _event=event):
            await persist_event(payload, _event)
        bus.subscribe(event, handler)
