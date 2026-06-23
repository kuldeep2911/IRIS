"""Orchestrator — the stateless agent loop (route -> tools -> answer).

GOLDEN RULE #3: all per-request state lives in the passed-in ``request`` +
:class:`RequestContext`; nothing is stored at module scope. The Orchestrator
object itself only holds injected, stateless collaborators (LLM client, MCPHost).

Flow per request:
  classify -> model_for -> loop up to MAX_STEPS:
    ask Gemini (with MCP tool schemas) -> if it requests tools, run them through
    the MCP host (confirmation-gated where required), feed results back -> repeat
    until the model returns a final answer or limits are hit.

Resilience: tool failures are fed back so the model can try another approach,
up to MAX_TOOL_ERRORS total, then we escalate gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from iris.config.settings import get_settings
from iris.core.confirm import is_payment, needs_confirmation
from iris.core.context import RequestContext, assemble, est_tokens
from iris.llm.base import LLMClient, ToolCall, Usage
from iris.mcp.host import MCPHost, ToolError
from iris.router.model_router import classify, model_for

log = structlog.get_logger(__name__)

MAX_STEPS = 8           # agent-loop iterations (model<->tools)
MAX_TOOL_ERRORS = 5     # total tool failures before escalating

_SYSTEM_PROMPT_TMPL = (
    "You are I.R.I.S. (Intelligent Responsive Intelligence System), a concise, "
    "capable personal AI assistant. You can call tools to act in the real world: "
    "read/write files and fetch web pages. Prefer tools over guessing.\n"
    "FILES: the only writable directory is the sandbox at '{workspace}'. Always "
    "use absolute paths inside it (e.g. '{workspace}\\notes.txt'). When asked to "
    "save something to a file, actually write the file there.\n"
    "WEB: to research a fact, fetch a relevant public URL directly — prefer a "
    "simple data source or content page (e.g. a public API or a world-clock / "
    "reference page) over search-engine result pages, which are often JS-heavy. "
    "If one URL fails, try another before giving up.\n"
    "After acting, give a short, direct summary. If you cannot complete a "
    "request, say so plainly."
)


def _system_prompt() -> str:
    from pathlib import Path

    workspace = str(Path(get_settings().WORKSPACE_DIR).resolve())
    return _SYSTEM_PROMPT_TMPL.format(workspace=workspace)


@dataclass
class Result:
    """The outcome of one orchestrated request."""

    text: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    request_class: str = ""
    steps: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class Orchestrator:
    """Runs the agent loop. Construct once with injected deps; call ``handle``."""

    def __init__(self, llm: LLMClient, mcp: MCPHost) -> None:
        self._llm = llm
        self._mcp = mcp

    async def handle(self, request: str, ctx: RequestContext) -> Result:
        assembled = assemble(request, ctx)
        rc = classify(request, est_tokens(assembled))
        choice = model_for(rc)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": self._render_user(assembled)},
        ]
        tools = self._mcp.schemas()

        total_usage = Usage()
        executed: list[dict[str, Any]] = []
        tool_errors = 0

        for step in range(1, MAX_STEPS + 1):
            resp = await self._llm.complete(
                choice.model,
                messages,
                tools=tools or None,
                max_output_tokens=choice.max_output_tokens,
            )
            total_usage = _add_usage(total_usage, resp.usage)

            if not resp.has_tool_calls:
                await ctx.emit("final", {"text": resp.text})
                return Result(
                    text=resp.text,
                    usage=total_usage,
                    model=resp.model or choice.model,
                    request_class=rc.name,
                    steps=step,
                    tool_calls=executed,
                )

            # Record the model's tool-call turn so the function_call/response pair
            # stays consistent in history.
            messages.append(_assistant_tool_turn(resp.text, resp.tool_calls))

            for call in resp.tool_calls:
                outcome = await self._run_call(call, ctx)
                executed.append({"name": call.name, "args": call.args, "outcome": outcome[:200]})
                messages.append(_tool_turn(call, outcome))
                if outcome.startswith("ERROR:"):
                    tool_errors += 1
                    if tool_errors >= MAX_TOOL_ERRORS:
                        text = "I hit repeated tool errors and couldn't complete that. " \
                               "Here's how far I got; please refine the request."
                        await ctx.emit("final", {"text": text, "escalated": True})
                        return Result(
                            text=text,
                            usage=total_usage,
                            model=choice.model,
                            request_class=rc.name,
                            steps=step,
                            tool_calls=executed,
                        )

        text = "(max steps reached without a final answer)"
        await ctx.emit("final", {"text": text, "max_steps": True})
        return Result(
            text=text,
            usage=total_usage,
            model=choice.model,
            request_class=rc.name,
            steps=MAX_STEPS,
            tool_calls=executed,
        )

    # ── single tool call: confirmation gate -> payment block -> invoke ────────
    async def _run_call(self, call: ToolCall, ctx: RequestContext) -> str:
        # GOLDEN RULE #7: payments are hard-blocked, no override.
        if is_payment(call.name):
            await ctx.emit("blocked", {"tool": call.name, "reason": "payment"})
            return "ERROR: payment/purchase actions are hard-blocked and will not be executed."

        # GOLDEN RULE #6: gate outward/destructive actions on confirmation.
        if needs_confirmation(call.name):
            await ctx.emit("confirm_request", {"tool": call.name, "args": call.args})
            if not await self._wait_or_autoskip(ctx, call):
                await ctx.emit("tool_result", {"tool": call.name, "status": "denied"})
                return "DENIED: this action requires user confirmation and was not executed."

        try:
            result = await self._mcp.invoke(call.name, call.args)
            await ctx.emit("tool_result", {"tool": call.name, "status": "ok"})
            return result
        except ToolError as exc:
            log.warning("orchestrator.tool_error", tool=call.name, error=str(exc))
            await ctx.emit("tool_result", {"tool": call.name, "status": "error", "error": str(exc)})
            # Feed the error back so the model can try an alternative approach.
            return f"ERROR: {exc}"

    async def _wait_or_autoskip(self, ctx: RequestContext, call: ToolCall) -> bool:
        """Resolve a confirmation. No interactive channel yet -> use ctx policy.

        Defaults to DENY (safe). A real confirm flow (WebSocket) plugs in here in
        a later phase without changing the loop.
        """
        return bool(ctx.auto_confirm)

    @staticmethod
    def _render_user(assembled: dict[str, Any]) -> str:
        # Context block (memory/screen) gets prepended here in later phases.
        return str(assembled.get("request", ""))


# ── message helpers ──────────────────────────────────────────────────────────
def _assistant_tool_turn(text: str, tool_calls: list[ToolCall]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": text or "",
        "tool_calls": [{"name": c.name, "args": c.args} for c in tool_calls],
    }


def _tool_turn(call: ToolCall, content: str) -> dict[str, Any]:
    return {"role": "tool", "name": call.name, "content": content}


def _add_usage(a: Usage, b: Usage) -> Usage:
    return Usage(input_tok=a.input_tok + b.input_tok, output_tok=a.output_tok + b.output_tok)
