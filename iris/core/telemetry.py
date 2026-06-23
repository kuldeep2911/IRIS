"""OpenTelemetry tracing setup + helper (gateway -> router -> orchestrator ->
mcp -> llm).

A single ``setup_tracing()`` installs a tracer provider; ``span(name, **attrs)``
is a small context manager used at each boundary so a request produces one trace
across the whole stack. With no exporter configured the spans are cheap no-ops,
so this never slows a request or requires a collector to run.

Structured logs (request id + tenant id) are handled by structlog contextvars in
``security/redaction.configure_logging`` — together they give full observability.
"""

from __future__ import annotations

import contextlib
from typing import Any

_configured = False


def setup_tracing(service_name: str = "iris", console: bool = False) -> None:
    """Install an OpenTelemetry tracer provider once. Idempotent + safe."""
    global _configured
    if _configured:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if console:
            from opentelemetry.sdk.trace.export import (
                ConsoleSpanExporter,
                SimpleSpanProcessor,
            )

            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _configured = True
    except Exception:  # noqa: BLE001 — tracing must never break startup
        _configured = True  # don't retry on every call


@contextlib.contextmanager
def span(name: str, **attributes: Any):
    """Start a span across a boundary; no-op if OTel isn't available."""
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("iris")
        with tracer.start_as_current_span(name) as sp:
            for k, v in attributes.items():
                if v is not None:
                    sp.set_attribute(k, v)
            yield sp
    except Exception:  # noqa: BLE001
        yield None
