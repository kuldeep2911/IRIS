"""Provider-agnostic LLM interface (GOLDEN RULE #10).

Everything in the core talks to an ``LLMClient``; the concrete provider (Gemini
today) is constructed only by ``iris.llm.get_llm()``. Swapping providers means
writing one new ``LLMClient`` subclass — no caller changes.

Message shape (a list of dicts), kept minimal and provider-neutral::

    {"role": "system" | "user" | "assistant" | "tool", "content": str, ...}

Tool/assistant turns may also carry ``tool_calls``; tool turns carry
``tool_call_id`` / ``name``. Each provider adapter maps this to its own format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

# A single chat message. Provider-neutral; adapters translate it.
Message = dict[str, Any]
# A tool/function schema (name, description, JSON-schema parameters).
ToolSchema = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A model request to call a tool — ``{name, args}`` with a stable id."""

    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class Usage:
    """Token accounting for one completion."""

    input_tok: int = 0
    output_tok: int = 0

    @property
    def total_tok(self) -> int:
        return self.input_tok + self.output_tok


@dataclass
class LLMResponse:
    """Normalized completion result — identical across providers."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: Any = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(ABC):
    """Abstract chat-completion client. One method, normalized output."""

    @abstractmethod
    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema] | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        """Run a completion and return a normalized :class:`LLMResponse`.

        ``model`` always comes from ``router.model_router.model_for(...)`` — the
        adapter never chooses or hardcodes a model id (GOLDEN RULE #2).
        """
        raise NotImplementedError
