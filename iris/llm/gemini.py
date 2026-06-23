"""GeminiClient — google-genai adapter implementing :class:`LLMClient`.

- Reads ``GEMINI_API_KEY`` from settings ONLY (GOLDEN RULE #8); never os.environ.
- Maps our neutral message + tool schemas to Gemini's function-calling format.
- Returns a normalized :class:`LLMResponse` (text + tool_calls + usage).
- Resilience: exponential backoff on 429/5xx, a circuit breaker, request timeout.
- Usage: optional ``usage_sink`` callback so the data layer can write a usage
  row later (Phase 1.3) without this module importing the data layer.

NOTE: model ids are NOT chosen here — the caller passes one from the router.
"""

from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

import structlog

from iris.config.settings import get_settings
from iris.llm.base import (
    LLMClient,
    LLMResponse,
    Message,
    ToolCall,
    ToolSchema,
    Usage,
)

log = structlog.get_logger(__name__)

# usage_sink(model, usage) -> None | Awaitable[None]
UsageSink = Callable[[str, Usage], None | Awaitable[None]]

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class _CircuitBreaker:
    """Trip after N consecutive failures; fail fast during the cooldown window.

    This is resilience state on a long-lived adapter instance — NOT per-request
    state — so it does not violate the stateless-core rule.
    """

    fail_threshold: int = 5
    cooldown_seconds: float = 30.0
    _consecutive_failures: int = 0
    _opened_at: float | None = field(default=None)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if monotonic() - self._opened_at >= self.cooldown_seconds:
            # half-open: allow a trial call
            self._opened_at = None
            self._consecutive_failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.fail_threshold:
            self._opened_at = monotonic()


class CircuitOpenError(RuntimeError):
    """Raised when the breaker is open and the call is rejected fast."""


class GeminiClient(LLMClient):
    """Async Gemini chat client behind the provider-agnostic interface."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        usage_sink: UsageSink | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 4,
    ) -> None:
        # GOLDEN RULE #8: the key comes from settings, nowhere else.
        self._api_key = api_key if api_key is not None else get_settings().GEMINI_API_KEY
        self._usage_sink = usage_sink
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._breaker = _CircuitBreaker()
        self._client: Any | None = None  # lazily constructed google-genai Client

    # ── public API ───────────────────────────────────────────────────────────
    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema] | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        if self._breaker.is_open:
            raise CircuitOpenError("Gemini circuit breaker is open; refusing call.")

        from google.genai import types  # lazy import keeps module import cheap

        client = self._get_client()
        system_instruction, contents = self._to_gemini_contents(messages, types)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            max_output_tokens=max_output_tokens,
            tools=self._to_gemini_tools(tools, types),
        )

        raw = await self._call_with_resilience(client, model, contents, config)
        response = self._normalize(raw, model)
        await self._emit_usage(model, response.usage)
        return response

    # ── resilience: retries + breaker + timeout ──────────────────────────────
    async def _call_with_resilience(
        self, client: Any, model: str, contents: Any, config: Any
    ) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                raw = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    ),
                    timeout=self._timeout,
                )
                self._breaker.record_success()
                return raw
            except asyncio.TimeoutError as exc:
                last_exc = exc
                self._breaker.record_failure()
                log.warning("gemini.timeout", model=model, attempt=attempt)
            except Exception as exc:  # noqa: BLE001 — classify then maybe retry
                last_exc = exc
                if not _is_retryable(exc):
                    self._breaker.record_failure()
                    raise
                self._breaker.record_failure()
                log.warning(
                    "gemini.retryable_error",
                    model=model,
                    attempt=attempt,
                    error=str(exc),
                )
            if attempt < self._max_retries:
                await asyncio.sleep(_backoff_delay(attempt))
        assert last_exc is not None
        raise last_exc

    # ── mapping: our messages -> Gemini ──────────────────────────────────────
    @staticmethod
    def _to_gemini_contents(messages: Sequence[Message], types: Any) -> tuple[str, list[Any]]:
        """Split out the system instruction; map the rest to Gemini contents."""
        system_parts: list[str] = []
        contents: list[Any] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "") or ""
            if role == "system":
                if content:
                    system_parts.append(content)
                continue
            if role == "tool":
                # A tool/function result -> function_response part.
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=msg.get("name", "tool"),
                                response=_as_response_dict(content),
                            )
                        ],
                    )
                )
                continue
            gem_role = "model" if role in ("assistant", "model") else "user"
            parts: list[Any] = []
            if content:
                parts.append(types.Part.from_text(text=content))
            for tc in msg.get("tool_calls", []) or []:
                parts.append(
                    types.Part.from_function_call(
                        name=tc.get("name", ""), args=tc.get("args", {})
                    )
                )
            if parts:
                contents.append(types.Content(role=gem_role, parts=parts))
        return "\n\n".join(system_parts), contents

    @staticmethod
    def _to_gemini_tools(tools: Sequence[ToolSchema] | None, types: Any) -> list[Any] | None:
        if not tools:
            return None
        declarations = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=_sanitize_schema(t.get("parameters") or t.get("input_schema")),
            )
            for t in tools
        ]
        return [types.Tool(function_declarations=declarations)]

    # ── mapping: Gemini -> our LLMResponse ───────────────────────────────────
    @staticmethod
    def _normalize(raw: Any, model: str) -> LLMResponse:
        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        for candidate in getattr(raw, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "text", None):
                    text_chunks.append(part.text)
                fn = getattr(part, "function_call", None)
                if fn is not None:
                    tool_calls.append(
                        ToolCall(name=fn.name, args=dict(fn.args or {}), id=getattr(fn, "id", None))
                    )

        meta = getattr(raw, "usage_metadata", None)
        usage = Usage(
            input_tok=getattr(meta, "prompt_token_count", 0) or 0,
            output_tok=getattr(meta, "candidates_token_count", 0) or 0,
        )
        return LLMResponse(
            text="".join(text_chunks),
            tool_calls=tool_calls,
            usage=usage,
            model=model,
            raw=raw,
        )

    # ── usage sink ───────────────────────────────────────────────────────────
    async def _emit_usage(self, model: str, usage: Usage) -> None:
        if self._usage_sink is None:
            return
        try:
            result = self._usage_sink(model, usage)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001 — usage logging must never break a reply
            log.warning("gemini.usage_sink_failed", error=str(exc))

    # ── lazy client ──────────────────────────────────────────────────────────
    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY is not set. Add it to .env (read via "
                    "iris.config.settings — never elsewhere)."
                )
            from google import genai  # lazy import

            self._client = genai.Client(api_key=self._api_key)
        return self._client


# ── module helpers ───────────────────────────────────────────────────────────
def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and code in _RETRYABLE_STATUS:
        return True
    text = str(exc).lower()
    return any(str(s) in text for s in _RETRYABLE_STATUS) or "unavailable" in text


def _backoff_delay(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(cap, base * (2 ** (attempt - 1))))


def _as_response_dict(content: Any) -> dict[str, Any]:
    return content if isinstance(content, dict) else {"result": content}


# JSON-schema keys Gemini's function-calling accepts; everything else (e.g.
# "$schema", "additionalProperties", "title", "default") triggers a 400 and is
# stripped so raw MCP inputSchemas can be passed straight through.
_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "type", "format", "description", "nullable", "enum", "items",
        "properties", "required", "anyOf", "minimum", "maximum",
        "minItems", "maxItems", "minLength", "maxLength", "pattern",
    }
)


def _sanitize_schema(schema: Any) -> Any:
    """Recursively keep only Gemini-supported JSON-schema keys.

    Returns ``None`` for an object schema with no usable properties so no-arg
    tools declare cleanly instead of sending an empty object.
    """
    if not isinstance(schema, dict):
        return schema
    clean: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _ALLOWED_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            clean[key] = {k: _sanitize_schema(v) for k, v in value.items()}
        elif key in ("items",):
            clean[key] = _sanitize_schema(value)
        elif key == "anyOf" and isinstance(value, list):
            clean[key] = [_sanitize_schema(v) for v in value]
        else:
            clean[key] = value
    if clean.get("type") == "object" and not clean.get("properties"):
        return None
    return clean
