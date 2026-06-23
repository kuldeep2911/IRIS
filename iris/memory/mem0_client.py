"""Mem0-style AUDN learning loop (Add / Update / Delete / No-op).

After every turn IRIS learns: it extracts durable user facts from the turn and
reconciles them against existing memories so the store stays fresh and free of
contradictions (inspired by Hermes' continuous learning + Mem0's AUDN).

Privacy (GOLDEN RULE #5): the turn is sanitised locally before anything reaches
Gemini — no raw secrets. Extraction uses the router's CHEAP model (GOLDEN RULE:
cheapest capable) via the injected provider-agnostic LLM client.

This is the self-hosted AUDN loop over our agentmemory store; it does not depend
on the external mem0ai package (which would pull its own LLM/vector config).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from iris.llm.base import LLMClient
from iris.memory.store import MemoryStore
from iris.router.model_router import RequestClass, model_for
from iris.security.redaction import _redact_text

log = structlog.get_logger(__name__)

_MAX_TURN_CHARS = 4000  # truncate before extraction (no giant raw bodies)

_SYSTEM = (
    "You maintain a user's long-term memory of DURABLE facts: stable preferences, "
    "relationships, identity, and recurring work/context. Ignore one-off task "
    "details, questions, greetings, and transient info. Reconcile each candidate "
    "fact against the existing memories provided:\n"
    "- duplicates an existing memory -> NOOP\n"
    "- updates/contradicts an existing memory -> UPDATE that memory's id (or "
    "DELETE it if simply no longer true)\n"
    "- genuinely new durable fact -> ADD\n"
    "Write facts in third person, concise (e.g. 'The user prefers light mode'). "
    "Output ONLY a JSON array of operations, no prose."
)


class Mem0Client:
    """The write-path learner. Construct with an LLM client + MemoryStore."""

    def __init__(self, llm: LLMClient, memory: MemoryStore) -> None:
        self._llm = llm
        self._memory = memory

    async def learn(self, tenant_id: str, user_id: str | None, turn: dict | str) -> dict[str, Any]:
        """Extract + reconcile durable facts from a turn. Returns an op summary."""
        if not self._memory.available:
            return {"skipped": "memory_unavailable"}

        summary = _summarise_turn(turn)
        if not summary.strip():
            return {"ops": 0}

        # Recall existing memories related to this turn for reconciliation.
        existing = await self._memory.recall(tenant_id, summary, k=8)
        existing_block = "\n".join(f"{m.id}: {m.text}" for m in existing) or "(none)"

        ops = await self._extract_ops(summary, existing_block)
        applied = await self._apply_ops(tenant_id, user_id, ops)
        if any(applied.values()):
            log.info("mem0.learned", tenant_id=tenant_id, **applied)
        return {"ops": ops, "applied": applied}

    # ── extraction (cheap model + sanitiser) ─────────────────────────────────
    async def _extract_ops(self, summary: str, existing_block: str) -> list[dict[str, Any]]:
        choice = model_for(RequestClass.SIMPLE)  # cheap Flash-Lite
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Existing memories (id: text):\n{existing_block}\n\n"
                    f"Conversation turn:\n{summary}\n\n"
                    'Return JSON array. Each item: {"action":"ADD|UPDATE|DELETE|NOOP",'
                    ' "text":"...", "id":"..."}. Empty array if nothing durable.'
                ),
            },
        ]
        try:
            resp = await self._llm.complete(
                choice.model, messages, max_output_tokens=choice.max_output_tokens
            )
            return _parse_ops(resp.text)
        except Exception as exc:  # noqa: BLE001 — learning must never break a reply
            log.warning("mem0.extract_failed", error=str(exc))
            return []

    # ── apply AUDN ops to the store ──────────────────────────────────────────
    async def _apply_ops(
        self, tenant_id: str, user_id: str | None, ops: list[dict[str, Any]]
    ) -> dict[str, int]:
        counts = {"added": 0, "updated": 0, "deleted": 0, "noop": 0}
        for op in ops:
            action = str(op.get("action", "")).upper()
            text = (op.get("text") or "").strip()
            mem_id = op.get("id")
            try:
                if action == "ADD" and text:
                    await self._memory.remember(
                        tenant_id, user_id, text, source="mem0", confidence=0.8
                    )
                    counts["added"] += 1
                elif action == "UPDATE" and mem_id and text:
                    await self._memory.update(tenant_id, mem_id, text=text, confidence=0.85)
                    counts["updated"] += 1
                elif action == "DELETE" and mem_id:
                    await self._memory.forget(tenant_id, mem_id)
                    counts["deleted"] += 1
                else:
                    counts["noop"] += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("mem0.apply_failed", action=action, error=str(exc))
        return counts


# ── helpers ──────────────────────────────────────────────────────────────────
def _summarise_turn(turn: dict | str) -> str:
    """Locally build a compact, SANITISED turn summary (no raw secrets/bodies)."""
    if isinstance(turn, str):
        text = turn
    else:
        user = turn.get("user", "")
        assistant = turn.get("assistant", "")
        text = f"User: {user}\nAssistant: {assistant}"
    return _redact_text(text[:_MAX_TURN_CHARS])


def _parse_ops(text: str) -> list[dict[str, Any]]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("[") : raw.rfind("]") + 1] if "[" in raw else raw
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(raw[start : end + 1])
        return [op for op in data if isinstance(op, dict)]
    except json.JSONDecodeError:
        return []
