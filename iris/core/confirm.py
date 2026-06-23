"""Confirmation policy (GOLDEN RULE #6) + payments hard-block (RULE #7).

A small, central policy the orchestrator consults before executing a tool call.
Outward / destructive / irreversible actions (send, delete, publish, post) and
anything payment-like require explicit user confirmation. Payment/purchase
actions are HARD-BLOCKED — never executed, even with confirmation.

Later phases extend the explicit sets (e.g. ``email_send``, ``calendar_delete``,
``whatsapp_send``) without touching the orchestrator.
"""

from __future__ import annotations

# Substrings that mark an action needing confirmation.
# Includes browser submission verbs (send/submit/post) so any browser action
# that submits a form or sends a message is gated (Phase 2.2).
_CONFIRM_KEYWORDS: tuple[str, ...] = (
    "send", "submit", "delete", "publish", "post", "remove", "destroy", "drop",
)

# Explicit tool names that always require confirmation (extended per phase).
# Browser submit/login-commit tools land here as the servers expose them.
_CONFIRM_TOOLS: frozenset[str] = frozenset(
    {
        "browser_file_upload",   # uploading a file is an outward action
    }
)

# Payment / purchase signals — HARD-BLOCKED (GOLDEN RULE #7).
_PAYMENT_KEYWORDS: tuple[str, ...] = (
    "pay", "payment", "purchase", "buy", "checkout", "order_now",
    "transfer_money", "wire", "charge_card",
)
_PAYMENT_BLOCK_EXEMPT: frozenset[str] = frozenset()  # e.g. read-only "order_status"


def is_payment(tool_name: str) -> bool:
    """True if the tool looks payment/purchase-related (always blocked)."""
    name = (tool_name or "").lower()
    if name in _PAYMENT_BLOCK_EXEMPT:
        return False
    return any(kw in name for kw in _PAYMENT_KEYWORDS)


def needs_confirmation(tool_name: str) -> bool:
    """True if this tool call must be confirmed by the user before executing."""
    name = (tool_name or "").lower()
    if name in _CONFIRM_TOOLS:
        return True
    return any(kw in name for kw in _CONFIRM_KEYWORDS)
