"""OpenTelemetry traces (ADR 0014): off by default, never carrying credentials or values.

The gateway keeps its own tracer provider instead of replacing the process-wide one, so it
can be switched on, off or swapped in tests without side effects.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

TRACER_NAME = "odoo_agent_gateway"
MODES = ("none", "console", "otlp")

_provider: TracerProvider | None = None


def use_provider(provider: TracerProvider | None) -> None:
    global _provider
    _provider = provider


def configure(mode: str | None) -> TracerProvider | None:
    """Switch tracing on for `console` or `otlp`. `none` (the default) leaves things as they are."""
    mode = (mode or "none").strip().lower()
    if mode == "none":
        return None
    if mode not in MODES:
        raise ValueError(f"GATEWAY_TRACES must be one of {', '.join(MODES)}, not {mode!r}.")
    provider = TracerProvider(resource=Resource.create({"service.name": "odoo-agent-gateway"}))
    if mode == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError as error:
            raise ValueError(
                "GATEWAY_TRACES=otlp needs the OTLP exporter: "
                "pip install 'odoo-agent-gateway[otlp]'"
            ) from error
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    use_provider(provider)
    return provider


def _tracer() -> trace.Tracer:
    return _provider.get_tracer(TRACER_NAME) if _provider else trace.NoOpTracer()


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """A span with the given attributes; dotted attribute names are passed with **{...}."""
    clean = {key: value for key, value in attributes.items() if value is not None}
    with _tracer().start_as_current_span(name, attributes=clean) as current:
        yield current


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
