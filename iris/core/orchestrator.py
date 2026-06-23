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

import asyncio

import structlog

from iris.config.settings import get_settings
from iris.agents.base import SubAgentRunner, load_specialists
from iris.core.confirm import is_payment, needs_confirmation
from iris.core.context import RequestContext, assemble, est_tokens
from iris.core.planner import SubTask, plan, should_delegate
from iris.core.privacy import summarise_tool_output
from iris.llm.base import LLMClient, ToolCall, Usage
from iris.mcp.host import MCPHost, ToolError
from iris.memory.mem0_client import Mem0Client
from iris.memory.store import MemoryStore
from iris.router.model_router import RequestClass, classify, model_for

log = structlog.get_logger(__name__)

MAX_STEPS = 8           # agent-loop iterations (model<->tools)
MAX_TOOL_ERRORS = 5     # total tool failures before escalating

# Strong refs to in-flight fire-and-forget learn tasks (GC safety only — not
# request state; cleared on completion).
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()

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
        self._memory = MemoryStore(mcp)
        self._mem0 = Mem0Client(llm, self._memory)
        self._specialists = load_specialists()
        self._subagents = SubAgentRunner(llm, mcp, self._specialists)

    async def handle(self, request: str, ctx: RequestContext) -> Result:
        ctx.memory = self._memory  # used by assemble() for recall
        assembled = await assemble(request, ctx)
        rc = classify(request, est_tokens(assembled))

        # Multi-agent path ONLY for genuinely hard, multi-part work (else cheap).
        if should_delegate(rc, request):
            return await self._handle_multi_agent(request, ctx, rc)

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
                # Learn from this turn (fire-and-forget; never blocks the reply).
                self._schedule_learn(ctx, request, resp.text)
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

    # ── commander / multi-agent path ─────────────────────────────────────────
    async def _handle_multi_agent(self, request: str, ctx: RequestContext, rc) -> Result:
        await self._emit_agent(ctx, "agent_start", "commander", "running", "planning sub-tasks")
        subtasks = await plan(request, self._llm, self._specialists)
        await self._emit_agent(
            ctx, "agent_update", "commander", "running",
            f"plan: {' -> '.join(s.specialist for s in subtasks)}",
        )

        total_usage = Usage()
        transcript: list[tuple[SubTask, str]] = []
        executed: list[dict[str, Any]] = []

        for st in subtasks:
            result = await self._delegate_with_review(st, ctx, transcript)
            total_usage = _add_usage(total_usage, result.usage)
            transcript.append((st, result.output))
            executed.append({"name": st.specialist, "args": {"instruction": st.instruction},
                             "outcome": (result.output or result.notes)[:200]})

        final_text, syn_usage = await self._synthesize(request, transcript, ctx)
        total_usage = _add_usage(total_usage, syn_usage)

        await self._emit_agent(ctx, "agent_complete", "commander", "ok",
                               f"{len(subtasks)} sub-task(s) complete")
        await ctx.emit("final", {"text": final_text})
        self._schedule_learn(ctx, request, final_text)
        return Result(
            text=final_text, usage=total_usage, model=model_for(RequestClass.HARD).model,
            request_class=rc.name, steps=len(subtasks), tool_calls=executed,
        )

    async def _delegate_with_review(self, subtask: SubTask, ctx: RequestContext,
                                    transcript: list[tuple[SubTask, str]]):
        instruction = subtask.instruction
        if transcript:
            prior = "\n".join(f"- {s.specialist}: {out[:200]}" for s, out in transcript[-3:])
            instruction = f"{subtask.instruction}\n\nContext from earlier steps:\n{prior}"

        result = await self._subagents.run(SubTask(subtask.specialist, instruction, subtask.needs), ctx)
        revisions = 0
        while revisions < 2:
            accepted, feedback = await self._review(subtask, result, ctx)
            if accepted and result.success:
                break
            revisions += 1
            await self._emit_agent(ctx, "agent_update", "commander", "running",
                                   f"revision {revisions} -> {subtask.specialist}")
            retry = (f"{instruction}\n\nThe commander's review: {feedback}\n"
                     "Revise and complete the task accordingly.")
            result = await self._subagents.run(SubTask(subtask.specialist, retry, subtask.needs), ctx)
        return result

    async def _review(self, subtask: SubTask, result, ctx: RequestContext) -> tuple[bool, str]:
        choice = model_for(RequestClass.STANDARD)
        messages = [
            {"role": "system", "content":
                "You are the commander reviewing a specialist's work. Decide if it satisfies "
                "the instruction. Reply with JSON: {\"accept\": true|false, \"feedback\": \"...\"}."},
            {"role": "user", "content":
                f"Instruction: {subtask.instruction}\n\nResult (success={result.success}):\n"
                f"{result.output[:1500]}"},
        ]
        try:
            resp = await self._llm.complete(choice.model, messages, max_output_tokens=256)
            import json
            raw = resp.text[resp.text.find("{"): resp.text.rfind("}") + 1]
            data = json.loads(raw)
            return bool(data.get("accept", True)), str(data.get("feedback", ""))
        except Exception:  # noqa: BLE001 — review must never block progress
            return True, ""

    async def _synthesize(self, request: str, transcript: list[tuple[SubTask, str]],
                          ctx: RequestContext) -> tuple[str, Usage]:
        choice = model_for(RequestClass.STANDARD)
        work = "\n\n".join(f"[{s.specialist}] {out}" for s, out in transcript)
        messages = [
            {"role": "system", "content":
                "You are IRIS summarising a multi-agent job for the user. Give a concise, "
                "direct answer describing what was done and where the results are."},
            {"role": "user", "content": f"Original request: {request}\n\nSpecialist outputs:\n{work}"},
        ]
        try:
            resp = await self._llm.complete(choice.model, messages,
                                            max_output_tokens=choice.max_output_tokens)
            return resp.text, resp.usage
        except Exception as exc:  # noqa: BLE001
            return f"Completed {len(transcript)} sub-task(s).", Usage()

    async def _emit_agent(self, ctx: RequestContext, event: str, agent_name: str,
                          status: str, summary: str) -> None:
        await ctx.emit(event, {
            "type": event, "agent_name": agent_name, "status": status,
            "elapsed_ms": 0, "summary": summary,
            "tenant_id": ctx.tenant_id, "session_id": ctx.session_id,
        })

    # ── single tool call: confirmation gate -> payment block -> invoke ────────
    async def _run_call(self, call: ToolCall, ctx: RequestContext) -> str:
        # GOLDEN RULE #7: payments are hard-blocked, no override.
        if is_payment(call.name):
            await self._emit_tool(ctx, "blocked", call.name, "blocked", "payment")
            return "ERROR: payment/purchase actions are hard-blocked and will not be executed."

        # GOLDEN RULE #6: gate outward/destructive actions on confirmation.
        if needs_confirmation(call.name):
            await self._emit_tool(ctx, "confirm_request", call.name, "confirm", "awaiting approval")
            if not await self._wait_or_autoskip(ctx, call):
                await self._emit_tool(ctx, "tool_result", call.name, "denied", "not confirmed")
                return "DENIED: this action requires user confirmation and was not executed."

        try:
            result = await self._mcp.invoke(call.name, call.args)
            # Privacy gate: strip raw email/chat bodies to summaries before the
            # result enters the prompt context (GOLDEN RULE #5).
            result = summarise_tool_output(call.name, result)
            await self._emit_tool(ctx, "tool_result", call.name, "ok", call.name)
            return result
        except ToolError as exc:
            log.warning("orchestrator.tool_error", tool=call.name, error=str(exc))
            await self._emit_tool(ctx, "tool_result", call.name, "error", f"{call.name}: {exc}")
            # Feed the error back so the model can try an alternative approach.
            return f"ERROR: {exc}"

    async def _emit_tool(self, ctx: RequestContext, event: str, tool: str,
                         status: str, summary: str) -> None:
        await ctx.emit(event, {
            "type": event, "agent_name": "iris", "tool": tool, "status": status,
            "summary": summary, "tenant_id": ctx.tenant_id, "session_id": ctx.session_id,
        })

    def _schedule_learn(self, ctx: RequestContext, request: str, reply: str) -> None:
        """Fire-and-forget the Mem0 AUDN learn loop for this turn."""
        if not self._memory.available:
            return
        turn = {"user": request, "assistant": reply}

        async def _run() -> None:
            try:
                await self._mem0.learn(ctx.tenant_id, ctx.user_id, turn)
            except Exception as exc:  # noqa: BLE001
                log.warning("orchestrator.learn_failed", error=str(exc))

        task = asyncio.create_task(_run())
        # Keep a reference so the task isn't GC'd mid-flight.
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

    async def _wait_or_autoskip(self, ctx: RequestContext, call: ToolCall) -> bool:
        """Resolve a confirmation. No interactive channel yet -> use ctx policy.

        Defaults to DENY (safe). A real confirm flow (WebSocket) plugs in here in
        a later phase without changing the loop.
        """
        return bool(ctx.auto_confirm)

    @staticmethod
    def _render_user(assembled: dict[str, Any]) -> str:
        request = str(assembled.get("request", ""))
        memory = assembled.get("memory") or []
        if not memory:
            return request
        facts = "\n".join(f"- {m}" for m in memory)
        return (
            "Known facts about the user (from memory; use if relevant, ignore if not):\n"
            f"{facts}\n\nUser request: {request}"
        )


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
