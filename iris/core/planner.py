"""Planner — break a complex request into ordered specialist sub-tasks.

The commander uses the HARD model (Pro) ONLY for genuine multi-part work; the
orchestrator's cheap heuristic (``should_delegate``) keeps everything else on the
direct path so most traffic stays on Flash/Flash-Lite (cost rule).

``plan(request, llm, specialists)`` -> ordered ``list[SubTask]`` where each task
names a specialist, an instruction, and ``needs`` (indices of prerequisites).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import structlog

from iris.agents.base import Specialist, load_specialists
from iris.llm.base import LLMClient
from iris.router.model_router import RequestClass, model_for

log = structlog.get_logger(__name__)

MAX_SUBTASKS = 6

# Signals that a request is genuinely multi-part (worth multi-agent planning).
_MULTIPART_SIGNALS = (
    " and then ", " then ", " after that ", ", then", " and deploy", " and publish",
    " and test", " and review", " and write ", " and build ", " and create ",
)
_BUILD_SIGNALS = ("build", "create", "implement", "design and", "deploy", "ship", "develop")


def is_multipart(request: str) -> bool:
    """Heuristic: does the request contain multiple distinct steps?"""
    t = (request or "").lower()
    if any(sig in t for sig in _MULTIPART_SIGNALS):
        return True
    # multiple build/action verbs + a conjunction suggests a multi-step project.
    verbs = sum(1 for v in _BUILD_SIGNALS if v in t)
    return verbs >= 1 and (" and " in t or "," in t) and len(t) > 60


def should_delegate(request_class: RequestClass, request: str) -> bool:
    """Route to multi-agent only when HARD *and* multi-part (else direct/cheap)."""
    return request_class == RequestClass.HARD and is_multipart(request)


@dataclass
class SubTask:
    specialist: str
    instruction: str
    needs: list[int] = field(default_factory=list)


_PLANNER_SYSTEM = (
    "You are IRIS's planner/commander. Break the user's request into the FEWEST "
    "ordered sub-tasks, each assigned to exactly ONE specialist. Only include "
    "steps that are truly needed. Each sub-task must be a concrete, self-contained "
    "instruction. Output ONLY a JSON array."
)


async def plan(
    request: str,
    llm: LLMClient,
    specialists: dict[str, Specialist] | None = None,
    max_subtasks: int = MAX_SUBTASKS,
) -> list[SubTask]:
    """Decompose ``request`` into ordered specialist sub-tasks (uses the HARD model)."""
    specialists = specialists or load_specialists()
    names = list(specialists)

    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Available specialists: {names}\n\n"
                f"User request: {request}\n\n"
                f"Return a JSON array (max {max_subtasks}) of "
                '{"specialist": <name>, "instruction": <text>, "needs": [<indices>]}.'
            ),
        },
    ]
    # Plan with the HARD model (Pro); if it's unavailable/slow, degrade to the
    # STANDARD model so planning still works rather than collapsing to one task.
    tasks: list[SubTask] = []
    for rc in (RequestClass.HARD, RequestClass.STANDARD):
        choice = model_for(rc)
        try:
            resp = await llm.complete(
                choice.model, messages, max_output_tokens=choice.max_output_tokens
            )
            tasks = _parse_plan(resp.text, names)
            if tasks:
                break
        except Exception as exc:  # noqa: BLE001 — try the cheaper model, then fall back
            log.warning("planner.attempt_failed", model=choice.model, error=str(exc))
    if not tasks:
        fallback = "backend" if "backend" in specialists else names[0]
        tasks = [SubTask(specialist=fallback, instruction=request)]
    return tasks[:max_subtasks]


def _parse_plan(text: str, valid_names: list[str]) -> list[SubTask]:
    raw = (text or "").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    tasks: list[SubTask] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        spec = str(item.get("specialist", "")).strip()
        instruction = str(item.get("instruction", "")).strip()
        if spec not in valid_names or not instruction:
            continue
        needs = [int(n) for n in item.get("needs", []) if isinstance(n, (int, float))]
        tasks.append(SubTask(specialist=spec, instruction=instruction, needs=needs))
    return tasks
