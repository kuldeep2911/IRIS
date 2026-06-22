"""FastAPI gateway — the smallest end-to-end path: HTTP -> router -> Gemini.

STEP 0.4: ``POST /chat`` classifies the message, lets the router pick the
cheapest capable model, calls Gemini, and returns the reply + model + usage +
request_class. No memory or MCP yet (Phase 1+). The core stays STATELESS — no
per-request state is held at module scope; ``session_id`` is echoed through.

In STEP 1.2 the direct Gemini call here is replaced by ``Orchestrator.handle``.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from iris import __version__
from iris.core.events import EventBus
from iris.gateway.middleware import TenantMiddleware
from iris.llm import get_llm
from iris.router.model_router import classify, model_for

SYSTEM_PROMPT = (
    "You are I.R.I.S. (Intelligent Responsive Intelligence System), a concise, "
    "capable personal AI assistant. Answer directly and helpfully. If you don't "
    "know something, say so plainly."
)


# ── request / response models ────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None


class UsageOut(BaseModel):
    input_tok: int
    output_tok: int
    total_tok: int


class ChatResponse(BaseModel):
    reply: str
    model: str
    usage: UsageOut
    request_class: str
    session_id: str | None = None


# ── app factory ──────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    """Build the FastAPI app. A factory keeps construction explicit/testable."""
    app = FastAPI(title="I.R.I.S.", version=__version__)
    app.add_middleware(TenantMiddleware)

    # One event bus per app instance (not module-global mutable state).
    app.state.event_bus = EventBus()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, request: Request) -> ChatResponse:
        tenant_id = request.state.tenant_id
        bus: EventBus = app.state.event_bus

        # Route: cheapest capable model for this request.
        rc = classify(req.message)
        choice = model_for(rc)

        await bus.publish(
            "chat_received",
            {"tenant_id": tenant_id, "session_id": req.session_id, "request_class": rc.name},
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": req.message},
        ]
        resp = await get_llm().complete(
            choice.model,
            messages,
            max_output_tokens=choice.max_output_tokens,
        )

        await bus.publish(
            "chat_answered",
            {"tenant_id": tenant_id, "model": resp.model, "total_tok": resp.usage.total_tok},
        )

        return ChatResponse(
            reply=resp.text,
            model=resp.model,
            usage=UsageOut(
                input_tok=resp.usage.input_tok,
                output_tok=resp.usage.output_tok,
                total_tok=resp.usage.total_tok,
            ),
            request_class=rc.name,
            session_id=req.session_id,
        )

    return app


# Uvicorn entry point: `uvicorn iris.gateway.api:app`
app = create_app()
