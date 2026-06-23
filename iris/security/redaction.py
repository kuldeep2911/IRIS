"""Log redaction (GOLDEN RULE #8: nothing secret in logs).

A structlog processor that scrubs secrets from every log event before it is
rendered: sensitive keys (``password``, ``token``, ``api_key`` …) are masked
wholesale, and value patterns (Google API keys, bearer tokens, the configured
``GEMINI_API_KEY`` value itself) are masked inside any string field.

``configure_logging()`` installs this processor as part of the structlog
pipeline, so EVERY ``log.*`` call across IRIS is redacted by construction.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import structlog

from iris.config.settings import get_settings

REDACTED = "***REDACTED***"

# Event-dict keys whose values are always masked.
_SECRET_KEY_HINTS: tuple[str, ...] = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "auth", "credential", "credentials", "cookie",
    "gemini_api_key", "access_key", "private_key",
)

# Value patterns to mask inside any string field.
_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),          # Google API key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),               # OpenAI-style key
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(?i)(password|passwd|token|secret)\s*[=:]\s*\S+"),
)


def _redact_text(text: str) -> str:
    settings = get_settings()
    key = settings.GEMINI_API_KEY
    if key and key in text:
        text = text.replace(key, REDACTED)
    for pattern in _VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: mask secret keys + secret-looking values."""
    for k, v in list(event_dict.items()):
        if any(hint in k.lower() for hint in _SECRET_KEY_HINTS):
            event_dict[k] = REDACTED
        elif isinstance(v, str):
            event_dict[k] = _redact_text(v)
    return event_dict


def configure_logging() -> None:
    """Install the structlog pipeline with redaction. Idempotent."""
    settings = get_settings()
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.is_prod
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL)
        ),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_processor,  # <- secrets scrubbed here, before rendering
            renderer,
        ],
        cache_logger_on_first_use=True,
    )
