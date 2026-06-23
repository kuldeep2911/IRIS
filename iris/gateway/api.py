"""FastAPI gateway — HTTP -> orchestrator (route -> MCP tools -> Gemini) -> reply.

STEP 1.2: ``POST /chat`` now runs the stateless :class:`Orchestrator`, which can
call MCP tools (filesystem, web fetch) before answering. The MCP host is
connected once at app startup (lifespan) and shared, read-only, across requests
— the core stays stateless (per-request state is the ``RequestContext`` value).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from iris import __version__
from iris.core.context import RequestContext
from iris.core.events import EventBus
from iris.core.orchestrator import Orchestrator
from iris.core.telemetry import setup_tracing, span
from iris.data.db import init_models, session_scope
from iris.data.repo import (
    MessageRepo,
    SessionRepo,
    TenantRepo,
    UsageRepo,
    UserRepo,
    record_usage,
    seed_defaults,
)
from iris.gateway.connectors_api import router as connectors_router
from iris.gateway.middleware import TenantMiddleware
from iris.gateway.ws import register_ws
from iris.llm import get_llm
from iris.mcp.host import MCPHost
from iris.security.audit import subscribe_audit
from iris.security.redaction import configure_logging

configure_logging()  # install the redaction-aware structlog pipeline early
setup_tracing()      # install the OpenTelemetry tracer provider

log = structlog.get_logger(__name__)


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
    steps: int
    session_id: str | None = None


# ── lifespan: connect the MCP mesh once, tear down on shutdown ────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Data layer: create tables + seed the default tenant/user.
    await init_models()
    tenant_id, user_id = await seed_defaults()
    log.info("data.ready", tenant_id=tenant_id)

    bus = EventBus()
    subscribe_audit(bus)  # persist agent/tool events to actions_audit
    mcp = MCPHost()
    health = await mcp.connect_all()
    log.info("mcp.host_ready", health=health)

    app.state.event_bus = bus
    app.state.mcp = mcp
    app.state.default_user_id = user_id
    # Usage rows are written per LLM call via the sink (tenant from contextvar).
    app.state.orchestrator = Orchestrator(llm=get_llm(usage_sink=record_usage), mcp=mcp)
    try:
        yield
    finally:
        await mcp.aclose()


# ── app factory ──────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(title="I.R.I.S.", version=__version__, lifespan=lifespan)
    app.add_middleware(TenantMiddleware)
    # CORS so the React dashboard (Vite :5173) can call the API in local dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:4173", "http://127.0.0.1:4173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_ws(app)  # /ws live Agent Monitor stream
    app.include_router(connectors_router)  # /connectors + OAuth callback

    @app.get("/health")
    async def health(request: Request) -> dict:
        mcp: MCPHost | None = getattr(request.app.state, "mcp", None)
        return {
            "status": "ok",
            "version": __version__,
            "mcp": mcp.health() if mcp else {},
        }

    @app.get("/tenants")
    async def tenants() -> list[dict]:
        """List tenants (for the Cost page tenant selector / per-tenant billing)."""
        async with session_scope() as s:
            rows = await TenantRepo(s).list_all()
            return [{"id": t.id, "name": t.name, "plan": t.plan} for t in rows]

    @app.get("/usage")
    async def usage(request: Request, tenant_id: str | None = None) -> dict:
        """Cost/usage aggregates for a tenant (defaults to the request's tenant)."""
        tid = tenant_id or request.state.tenant_id
        async with session_scope() as s:
            repo = UsageRepo(s)
            return {
                "tenant_id": tid,
                "totals": await repo.totals(tid),
                "by_model": await repo.by_model(tid),
                "by_day": await repo.by_day(tid),
            }

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, request: Request) -> ChatResponse:
        orchestrator: Orchestrator = request.app.state.orchestrator
        tenant_id = request.state.tenant_id
        user_id = getattr(request.app.state, "default_user_id", None)

        # Ensure a session row, then persist the user turn (tenant-scoped).
        async with session_scope() as s:
            sess = await SessionRepo(s).get_or_create(tenant_id, req.session_id, user_id)
            session_id = sess.id
            await MessageRepo(s).add(tenant_id, session_id, "user", req.message)

        ctx = RequestContext(
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            request_id=getattr(request.state, "request_id", None),
            bus=request.app.state.event_bus,
        )
        with span("gateway.chat", tenant_id=tenant_id, session_id=session_id):
            result = await orchestrator.handle(req.message, ctx)

        # Persist the assistant turn with model + output tokens.
        async with session_scope() as s:
            await MessageRepo(s).add(
                tenant_id,
                session_id,
                "assistant",
                result.text,
                model=result.model,
                input_tok=result.usage.input_tok,
                output_tok=result.usage.output_tok,
            )

        return ChatResponse(
            reply=result.text,
            model=result.model,
            usage=UsageOut(
                input_tok=result.usage.input_tok,
                output_tok=result.usage.output_tok,
                total_tok=result.usage.total_tok,
            ),
            request_class=result.request_class,
            steps=result.steps,
            session_id=session_id,
        )

    return app


# Uvicorn entry point: `uvicorn iris.gateway.api:app`
app = create_app()
