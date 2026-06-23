"""Tenant + request-id middleware.

Resolves a ``tenant_id`` and a per-request ``request_id`` and attaches them to
``request.state`` so the whole stack is tenant-scoped (GOLDEN RULE #4) and every
log line / trace can be correlated.

For now ``tenant_id`` is the configured ``DEFAULT_TENANT_ID`` (single-user). This
is the exact seam where real multi-tenant auth (JWT / API key -> tenant lookup)
slots in later — without changing anything downstream.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from iris.config.settings import get_settings
from iris.data.db import current_tenant_id

log = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
TENANT_ID_HEADER = "X-Tenant-ID"


class TenantMiddleware(BaseHTTPMiddleware):
    """Attach ``request.state.tenant_id`` and ``request.state.request_id``."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()

        # request id: honor an inbound one (tracing), else mint a fresh one.
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex

        # tenant resolution seam. Single-user => DEFAULT_TENANT_ID. Later: derive
        # from an authenticated principal (JWT/API key), never trust the header
        # blindly in prod.
        tenant_id = settings.DEFAULT_TENANT_ID

        request.state.request_id = request_id
        request.state.tenant_id = tenant_id

        # Bind tenant for the in-flight request (used by the usage sink) + logs.
        token = current_tenant_id.set(tenant_id)
        structlog.contextvars.bind_contextvars(
            request_id=request_id, tenant_id=tenant_id
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
            current_tenant_id.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TENANT_ID_HEADER] = tenant_id
        return response
