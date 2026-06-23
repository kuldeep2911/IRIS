"""Browser router — pick the RIGHT browser MCP server per task.

GOLDEN RULE #1 (MCP-first): IRIS never hand-rolls browsing. Three maintained
servers cover different needs; this chooses between them:

- ``browser_mcp``  — the real, logged-in Chrome session (via the BrowserMCP
  extension). Use when the target needs an existing authenticated session
  (Gmail, WhatsApp, LinkedIn, banking, any "my account" page).
- ``playwright``   — deterministic, accessibility-tree driven. Use for known,
  structured form/flows where reliability matters more than reasoning.
- ``browser_use``  — AI-driven agentic browsing. Use for unknown pages that
  need reasoning ("find the cheapest flight on this page").

``choose_browser(task)`` returns a server name the orchestrator passes as a hint
when a browser tool is selected. Pure function — no network, easy to test.
"""

from __future__ import annotations

BROWSER_MCP = "browser_mcp"
PLAYWRIGHT = "playwright"
BROWSER_USE = "browser_use"

# Authenticated / logged-in targets -> the real Chrome session.
_AUTH_SIGNALS: tuple[str, ...] = (
    "log in", "login", "log into", "sign in", "sign into", "my account",
    "gmail", "inbox", "email", "whatsapp", "linkedin", "facebook", "instagram",
    "twitter", "x.com", "bank", "banking", "paypal", "amazon order", "netflix",
    "github", "calendar", "dashboard", "authenticated", "logged in",
)

# Known structured form/flow work -> deterministic Playwright.
_STRUCTURED_SIGNALS: tuple[str, ...] = (
    "fill the form", "fill out the form", "fill in the form", "contact form",
    "submit the form", "form at", "checkout form", "registration form",
    "structured", "step-by-step form", "fill the contact",
)

# Open-ended reasoning over an unknown page -> agentic browser-use.
_REASONING_SIGNALS: tuple[str, ...] = (
    "find the cheapest", "find the best", "compare", "figure out", "research",
    "explore", "navigate this", "on this page", "decide", "cheapest flight",
    "best deal", "summarise this site", "summarize this site",
)


def choose_browser(task: str) -> str:
    """Return the browser server best suited to ``task``.

    Priority: authenticated target > known structured form > reasoning >
    default. Authentication wins because a logged-in session is required before
    anything else can succeed.
    """
    t = (task or "").lower()

    if _contains_any(t, _AUTH_SIGNALS):
        return BROWSER_MCP
    if _contains_any(t, _STRUCTURED_SIGNALS):
        return PLAYWRIGHT
    if _contains_any(t, _REASONING_SIGNALS):
        return BROWSER_USE
    # Default: agentic browser-use handles arbitrary unknown pages.
    return BROWSER_USE


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(n in haystack for n in needles)
