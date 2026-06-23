"""Specialist sub-agents — run one sub-task with scoped MCP tools.

GOLDEN RULE #1: sub-agents reuse the SAME MCP servers as the core; this file
adds no capability code, it just scopes the shared tools to a specialist's
allowed tags and runs a bounded mini agent-loop.

``SubAgentRunner.run(subtask, ctx)`` -> ``SubAgentResult{success, output,
artifacts, notes}``. The commander (orchestrator) reviews results and may ask
for revisions. Bounds: max 6 steps, per-sub-agent token cap, max nesting depth 2.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

from iris.config.settings import get_settings
from iris.core.confirm import is_payment, needs_confirmation
from iris.core.context import RequestContext
from iris.core.privacy import summarise_tool_output
from iris.llm.base import LLMClient, ToolCall, Usage
from iris.mcp.host import MCPHost, ToolError
from iris.router.model_router import RequestClass, model_for
from iris.security.sandbox import SandboxViolation, validate_tool_call

log = structlog.get_logger(__name__)

_SPECIALISTS_PATH = Path(__file__).resolve().parent / "specialists.yaml"

SUB_AGENT_MAX_STEPS = 6
# Cap on cumulative tokens across a sub-agent's steps (each step re-sends the
# growing context, so this is generous — code-writing agents need headroom).
SUB_AGENT_TOKEN_CAP = 200_000
MAX_NESTING_DEPTH = 2

# Map a specialist tool TAG to keywords matched against the tool name / server.
_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "filesystem": ("filesystem", "file", "directory", "read_", "write_", "edit_"),
    "code": ("filesystem", "file", "write_", "read_", "edit_"),
    "web": ("websearch", "fetch", "browser", "playwright"),
    "search": ("websearch", "fetch", "search", "browser"),
    "browser": ("browser", "playwright"),
    "memory": ("memory", "agentmemory"),
    "email": ("gmail", "email", "mail", "send_email"),
    "calendar": ("calendar", "event"),
    "desktop": ("desktop", "screenshot", "clipboard", "window", "open_app"),
    "deploy": ("filesystem", "file", "fetch", "browser"),
}


@dataclass
class Specialist:
    name: str
    system_prompt: str
    allowed_tool_tags: list[str] = field(default_factory=list)


@dataclass
class SubAgentResult:
    success: bool
    output: str
    artifacts: list[str] = field(default_factory=list)
    notes: str = ""
    usage: Usage = field(default_factory=Usage)


def load_specialists(path: Path | None = None) -> dict[str, Specialist]:
    """Load the 12 specialists from specialists.yaml (name -> Specialist)."""
    data = yaml.safe_load((path or _SPECIALISTS_PATH).read_text(encoding="utf-8")) or {}
    out: dict[str, Specialist] = {}
    for name, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        out[name] = Specialist(
            name=name,
            system_prompt=(cfg.get("system_prompt") or "").strip(),
            allowed_tool_tags=list(cfg.get("allowed_tool_tags") or []),
        )
    return out


class SubAgentRunner:
    """Runs a single specialist sub-task with a bounded, tool-scoped agent loop."""

    def __init__(
        self,
        llm: LLMClient,
        mcp: MCPHost,
        specialists: dict[str, Specialist] | None = None,
    ) -> None:
        self._llm = llm
        self._mcp = mcp
        self._specialists = specialists or load_specialists()

    async def run(self, subtask: Any, ctx: RequestContext, depth: int = 0) -> SubAgentResult:
        spec = self._specialists.get(subtask.specialist)
        if spec is None:
            return SubAgentResult(False, "", notes=f"unknown specialist '{subtask.specialist}'")
        if depth >= MAX_NESTING_DEPTH:
            return SubAgentResult(False, "", notes="max nesting depth reached")

        started = time.monotonic()
        await _emit(ctx, "agent_start", spec.name, "running", f"start: {subtask.instruction[:80]}")

        tools = self._scoped_schemas(spec.allowed_tool_tags)
        messages = [
            {"role": "system", "content": self._system(spec)},
            {"role": "user", "content": subtask.instruction},
        ]
        choice = model_for(RequestClass.STANDARD)  # workhorse; commander uses HARD
        usage = Usage()
        artifacts: list[str] = []

        for step in range(1, SUB_AGENT_MAX_STEPS + 1):
            try:
                resp = await self._llm.complete(
                    choice.model, messages, tools=tools or None,
                    max_output_tokens=choice.max_output_tokens,
                )
            except Exception as exc:  # noqa: BLE001 — transient API error -> failed result, not a crash
                await _emit(ctx, "agent_failed", spec.name, "failed", f"llm error: {exc}")
                return SubAgentResult(False, "", artifacts, f"llm error: {exc}", usage)
            usage = _add(usage, resp.usage)
            if usage.total_tok > SUB_AGENT_TOKEN_CAP:
                await _emit(ctx, "agent_failed", spec.name, "failed", "token cap exceeded")
                return SubAgentResult(False, resp.text, artifacts, "token cap exceeded", usage)

            if not resp.has_tool_calls:
                elapsed = int((time.monotonic() - started) * 1000)
                await _emit(ctx, "agent_complete", spec.name, "ok",
                            f"done in {step} step(s)", elapsed)
                return SubAgentResult(True, resp.text, artifacts, "", usage)

            messages.append({
                "role": "assistant", "content": resp.text or "",
                "tool_calls": [{"name": c.name, "args": c.args} for c in resp.tool_calls],
            })
            for call in resp.tool_calls:
                outcome = await self._run_tool(call, ctx, spec.name)
                if call.name.startswith("write_") and isinstance(call.args, dict):
                    p = call.args.get("path")
                    if p:
                        artifacts.append(str(p))
                messages.append({"role": "tool", "name": call.name, "content": outcome})

        await _emit(ctx, "agent_failed", spec.name, "failed", "max steps reached")
        return SubAgentResult(False, "(max steps reached)", artifacts, "max steps", usage)

    # ── tool execution (same gates as the core) ──────────────────────────────
    async def _run_tool(self, call: ToolCall, ctx: RequestContext, agent: str) -> str:
        if is_payment(call.name):
            await _emit(ctx, "tool_result", agent, "blocked", f"{call.name} (payment)")
            return "ERROR: payment/purchase actions are hard-blocked."
        try:
            validate_tool_call(call.name, call.args, server=self._mcp.server_for(call.name))
        except SandboxViolation as exc:
            await _emit(ctx, "tool_result", agent, "blocked", f"sandbox: {exc}")
            return f"ERROR: blocked by sandbox: {exc}"
        if needs_confirmation(call.name) and not ctx.auto_confirm:
            await _emit(ctx, "confirm_request", agent, "confirm", call.name)
            await _emit(ctx, "tool_result", agent, "denied", call.name)
            return "DENIED: action requires user confirmation."
        try:
            result = await self._mcp.invoke(call.name, call.args)
            result = summarise_tool_output(call.name, result)
            await _emit(ctx, "tool_result", agent, "ok", call.name)
            return result
        except ToolError as exc:
            await _emit(ctx, "tool_result", agent, "error", f"{call.name}: {exc}")
            return f"ERROR: {exc}"

    def _scoped_schemas(self, tags: list[str]) -> list[dict[str, Any]]:
        if not tags:
            return self._mcp.schemas()
        keywords: set[str] = set()
        for tag in tags:
            keywords.update(_TAG_KEYWORDS.get(tag, (tag,)))
        scoped = []
        for schema in self._mcp.schemas():
            name = schema.get("name", "")
            server = self._mcp.server_for(name) or ""
            hay = f"{server} {name}".lower()
            if any(kw in hay for kw in keywords):
                scoped.append(schema)
        return scoped

    def _system(self, spec: Specialist) -> str:
        workspace = str(Path(get_settings().WORKSPACE_DIR).resolve())
        return (
            f"{spec.system_prompt}\n\nYou are the '{spec.name}' specialist on the IRIS "
            f"team. The only writable directory is the sandbox at '{workspace}' — write "
            "real files there using absolute paths. Be concise; when done, summarise what "
            "you produced. Confirmation-gated actions (send/delete/publish/deploy) will be "
            "blocked unless the user has approved them."
        )


# ── shared helpers (also used by the commander in the orchestrator) ──────────
async def _emit(
    ctx: RequestContext, event: str, agent_name: str, status: str,
    summary: str = "", elapsed_ms: int = 0,
) -> None:
    await ctx.emit(event, {
        "type": event,
        "agent_name": agent_name,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "summary": summary,
        "tenant_id": ctx.tenant_id,
        "session_id": ctx.session_id,
    })


def _add(a: Usage, b: Usage) -> Usage:
    return Usage(input_tok=a.input_tok + b.input_tok, output_tok=a.output_tok + b.output_tok)
