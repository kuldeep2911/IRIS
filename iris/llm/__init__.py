"""LLM adapters — provider-agnostic interface; swap provider in ONE file.

Callers use :func:`get_llm` and never import a concrete client, so changing
provider is a single edit here (GOLDEN RULE #10).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from iris.llm.base import LLMClient, LLMResponse, Message, ToolCall, ToolSchema, Usage

__all__ = [
    "LLMClient",
    "LLMResponse",
    "Message",
    "ToolCall",
    "ToolSchema",
    "Usage",
    "get_llm",
]

UsageSink = Callable[[str, Usage], None | Awaitable[None]]


def get_llm(usage_sink: UsageSink | None = None) -> LLMClient:
    """Return the configured LLM client. The ONE place the provider is chosen."""
    from iris.llm.gemini import GeminiClient

    return GeminiClient(usage_sink=usage_sink)
