"""Model router — the single source of model selection.

GOLDEN RULE #2: No Gemini model id may appear ANYWHERE else in the codebase.
This module is intentionally the only place that names a model. Callers go
through ``classify()`` -> ``model_for()`` and never see a model id literal.

Cost posture (GOLDEN RULE: cheapest capable model):
- TRIVIAL / SIMPLE        -> Flash-Lite  (near-free: greetings, short Q&A)
- STANDARD               -> Flash       (the workhorse: most real tasks)
- HARD / LONG_CONTEXT    -> Pro         (used rarely, only when it pays off)
- BACKGROUND             -> Flash via Batch (50% off, non-urgent jobs)

Classification is a cheap, deterministic heuristic (length + keywords + context
size + explicit force). A Flash-Lite LLM classifier may be slotted in later
BEHIND the same ``classify()`` signature, so callers never change.

Thresholds come from ``settings`` (tunable without a code change / redeploy).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from iris.config.settings import Settings, get_settings


class RequestClass(str, Enum):
    """Routing tiers, cheapest first."""

    TRIVIAL = "TRIVIAL"            # greetings, wake-ack, the routing decision itself
    SIMPLE = "SIMPLE"             # short factual Q&A / chit-chat, single cheap answer
    STANDARD = "STANDARD"         # the workhorse: planning, tool calls, drafting
    HARD = "HARD"                 # genuinely complex reasoning / design
    LONG_CONTEXT = "LONG_CONTEXT" # very large context windows
    BACKGROUND = "BACKGROUND"     # non-urgent batch jobs (memory consolidation, nightly)


@dataclass(frozen=True)
class ModelChoice:
    """A concrete model selection. The ONLY object carrying a model id outward."""

    model: str
    max_output_tokens: int
    use_batch: bool = False


# ── The ONLY place Gemini model ids appear ───────────────────────────────────
# (model id, default max_output_tokens, use_batch)
MODEL_MAP: dict[RequestClass, ModelChoice] = {
    RequestClass.TRIVIAL: ModelChoice("gemini-2.5-flash-lite", 256),
    RequestClass.SIMPLE: ModelChoice("gemini-2.5-flash-lite", 1_024),
    RequestClass.STANDARD: ModelChoice("gemini-2.5-flash", 2_048),
    RequestClass.HARD: ModelChoice("gemini-3.1-pro", 8_192),
    RequestClass.LONG_CONTEXT: ModelChoice("gemini-3.1-pro", 8_192),
    RequestClass.BACKGROUND: ModelChoice("gemini-2.5-flash", 4_096, use_batch=True),
}


# ── Heuristic signals (keyword sets are intent hints, NOT model ids) ──────────
# Greetings / acknowledgements -> TRIVIAL.
_TRIVIAL_PATTERNS: frozenset[str] = frozenset(
    {
        "hi", "hii", "hey", "hello", "yo", "sup", "hey iris", "ok", "okay",
        "k", "cool", "nice", "great", "thanks", "thank you", "ty", "thx",
        "yes", "yeah", "yep", "yup", "no", "nope", "bye", "goodbye",
        "good morning", "good evening", "good night", "gm", "gn",
    }
)

# Genuine complexity -> HARD (Pro). Checked before action verbs.
_HARD_KEYWORDS: tuple[str, ...] = (
    "design", "architect", "architecture", "refactor", "optimize", "optimise",
    "debug", "migrate", "system design", "in depth", "in-depth", "comprehensive",
    "whole codebase", "entire codebase", "plan the build", "plan the full build",
    "build and deploy", "deploy it", "deploy to", "step-by-step plan",
    "research and write a report", "trade-off", "tradeoff", "strategy",
)

# Real work that the workhorse handles -> STANDARD (Flash).
_ACTION_VERBS: tuple[str, ...] = (
    "draft", "write", "send", "reply", "email", "message", "schedule", "create",
    "add", "search", "browse", "open", "fill", "summarize", "summarise", "find",
    "book", "order", "download", "install", "translate", "make", "set up",
    "remind", "fix", "build", "code", "generate", "compose", "update", "delete",
    "post", "publish", "fetch", "look up", "plan",
)

# Short-question starters -> lean SIMPLE when no action verb present.
_QUESTION_STARTERS: tuple[str, ...] = (
    "what", "who", "when", "where", "which", "how", "why", "is ", "are ",
    "do ", "does ", "can ", "could ", "define", "explain", "tell me",
)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) — cheap, no tokenizer needed."""
    return max(1, len(text) // 4)


def classify(
    request_text: str,
    context_token_estimate: int = 0,
    force: RequestClass | str | None = None,
) -> RequestClass:
    """Pick the cheapest capable tier for a request.

    Cheap heuristic first: explicit force > context size > complexity keywords >
    greeting > short Q&A > workhorse default. Signature is stable so an LLM
    classifier can later sit behind it without touching callers.
    """
    settings: Settings = get_settings()

    # 1. Explicit per-request force wins (RequestClass or its name).
    forced = _coerce_force(force) or _coerce_force(settings.ROUTER_FORCE_MODEL)
    if forced is not None:
        return forced

    text = (request_text or "").strip()
    lowered = text.lower()
    req_tokens = _estimate_tokens(text)
    total_tokens = req_tokens + max(0, context_token_estimate)

    # 2. Long context dominates — only Pro (or chunking) can hold it.
    if total_tokens >= settings.ROUTER_LONG_CONTEXT_TOKENS:
        return RequestClass.LONG_CONTEXT

    # 3. Genuine complexity, or a request so large it's effectively a big task.
    if _contains_any(lowered, _HARD_KEYWORDS):
        return RequestClass.HARD
    if req_tokens >= settings.ROUTER_STANDARD_MAX_TOKENS:
        return RequestClass.HARD

    # 4. Greetings / acknowledgements.
    if lowered in _TRIVIAL_PATTERNS or _is_trivial_phrase(lowered):
        return RequestClass.TRIVIAL

    # 5. Short pure Q&A / chit-chat with no action verb -> cheap Flash-Lite.
    if (
        req_tokens <= settings.ROUTER_SIMPLE_MAX_TOKENS
        and not _contains_any(lowered, _ACTION_VERBS)
        and _looks_like_question(lowered)
    ):
        return RequestClass.SIMPLE

    # 6. Default: the workhorse handles real tasks.
    return RequestClass.STANDARD


def model_for(rc: RequestClass) -> ModelChoice:
    """Map a RequestClass to its concrete ModelChoice (the only model-id exit)."""
    choice = MODEL_MAP[rc]
    # Let settings tighten the default output cap globally without a code change.
    cap = min(choice.max_output_tokens, get_settings().ROUTER_DEFAULT_MAX_OUTPUT_TOKENS) \
        if rc in (RequestClass.TRIVIAL, RequestClass.SIMPLE) else choice.max_output_tokens
    if cap == choice.max_output_tokens:
        return choice
    return ModelChoice(choice.model, cap, choice.use_batch)


# ── helpers ──────────────────────────────────────────────────────────────────
def _coerce_force(force: RequestClass | str | None) -> RequestClass | None:
    if force is None:
        return None
    if isinstance(force, RequestClass):
        return force
    try:
        return RequestClass[str(force).strip().upper()]
    except KeyError:
        return None


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(n in haystack for n in needles)


def _looks_like_question(lowered: str) -> bool:
    return lowered.endswith("?") or lowered.startswith(_QUESTION_STARTERS)


def _is_trivial_phrase(lowered: str) -> bool:
    """Very short greeting-like phrase: <= 3 words and starts with a greeting."""
    words = lowered.replace("!", "").replace(".", "").split()
    return len(words) <= 3 and bool(words) and words[0] in _TRIVIAL_PATTERNS
