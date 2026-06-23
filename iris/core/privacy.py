"""Privacy filter for tool output (GOLDEN RULE #5).

Raw email / chat / message bodies must never reach Gemini — only sanitised
summaries (subject + sender + snippet). This filter runs on a tool's result the
moment it enters the prompt context (in the orchestrator loop), so the model
sees structure, not full bodies.

Two layers, always applied to read-type comms tools:
- secrets redaction (reuses the logging redactor), and
- body stripping: JSON results keep id/subject/from/to/date/snippet but drop
  body/payload/html fields; long string values are clipped to a snippet.
Non-comms tools pass through with redaction only.
"""

from __future__ import annotations

import json
from typing import Any

from iris.security.redaction import _redact_text

_SNIPPET = 240          # max chars kept from any single field / plain-text body
_MAX_OUTPUT = 6000      # overall cap on a comms read result

# A tool is a "read comms" tool if its name signals reading AND a comms channel.
_READ_SIGNALS = ("read", "search", "list", "get", "fetch", "recent", "unread", "history")
_COMMS_SIGNALS = ("mail", "email", "message", "msg", "thread", "inbox", "whatsapp", "chat")

# Keys whose values are bodies -> dropped entirely.
_BODY_KEYS = frozenset(
    {"body", "payload", "raw", "html", "htmlbody", "textbody", "fullbody",
     "content", "message_body", "text_body", "html_body"}
)
# Keys worth keeping verbatim (subject/sender/snippet/etc).
_KEEP_KEYS = frozenset(
    {"id", "threadid", "thread_id", "subject", "from", "sender", "to", "date",
     "snippet", "labels", "unread", "name", "title", "start", "end", "summary"}
)


def is_read_comms_tool(tool_name: str) -> bool:
    name = (tool_name or "").lower()
    return any(r in name for r in _READ_SIGNALS) and any(c in name for c in _COMMS_SIGNALS)


def summarise_tool_output(tool_name: str, text: str) -> str:
    """Redact secrets always; strip bodies to summaries for read-comms tools."""
    redacted = _redact_text(text or "")
    if not is_read_comms_tool(tool_name):
        return redacted
    try:
        data = json.loads(redacted)
    except (json.JSONDecodeError, TypeError):
        return _clip(redacted, _MAX_OUTPUT)
    return _clip(json.dumps(_strip_bodies(data)), _MAX_OUTPUT)


def _strip_bodies(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key = str(k).lower().replace(" ", "")
            if key in _BODY_KEYS:
                continue  # drop full bodies
            if isinstance(v, (dict, list)):
                out[k] = _strip_bodies(v)
            elif isinstance(v, str) and key not in _KEEP_KEYS:
                out[k] = _clip(v, _SNIPPET)
            else:
                out[k] = v
        return out
    if isinstance(obj, list):
        return [_strip_bodies(x) for x in obj]
    return obj


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + " …[summarised for privacy]"
