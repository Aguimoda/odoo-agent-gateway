import json

import httpx2
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.testclient import TestClient

from odoo_agent_gateway import tracing
from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.audit import MemoryAuditSink
from odoo_agent_gateway.config import Settings

KEY = "ana-secret-key-0123456789"
SETTINGS = Settings(odoo_url="http://odoo.test", odoo_db="demo")


def fake_odoo() -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        params = json.loads(request.content)["params"]
        if params["service"] == "common":
            result = 8 if params["args"][2] == KEY else False
        else:
            result = [{"id": 21, "display_name": "S00021"}]
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": None, "result": result})

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing.use_provider(provider)
    yield exporter
    tracing.use_provider(None)


def search(audit, key=KEY):
    app = create_app(SETTINGS, http_client_factory=fake_odoo, audit_sink=audit)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "x-odoo-login": "ana",
        "authorization": f"Bearer {key}",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_records",
            "arguments": {"model": "sale.order", "domain": [["name", "=", "S00021"]]},
        },
    }
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        client.post("/mcp", json=body, headers=headers)


def by_name(exporter):
    return {span.name: span for span in exporter.get_finished_spans()}


def test_a_call_produces_a_span_with_odoo_children(spans):
    audit = MemoryAuditSink()

    search(audit)

    named = by_name(spans)
    root = named["gateway.search_records"]
    assert root.attributes["gateway.tool"] == "search_records"
    assert root.attributes["gateway.outcome"] == "ok"
    odoo = [s for s in spans.get_finished_spans() if s.name == "odoo.rpc"]
    assert [s.attributes["odoo.method"] for s in odoo] == ["authenticate", "search_read"]
    assert odoo[1].attributes["odoo.model"] == "sale.order"
    assert all(s.parent.span_id == root.context.span_id for s in odoo)


def test_the_audit_row_carries_the_trace_id(spans):
    audit = MemoryAuditSink()

    search(audit)

    root = by_name(spans)["gateway.search_records"]
    assert audit.events[0].trace_id == format(root.context.trace_id, "032x")


def test_failures_are_traced_with_their_code(spans):
    search(MemoryAuditSink(), key="made-up-key")

    assert (
        by_name(spans)["gateway.search_records"].attributes["gateway.outcome"] == "unauthenticated"
    )


def test_traces_never_contain_keys_or_argument_values(spans):
    search(MemoryAuditSink())

    for span in spans.get_finished_spans():
        text = json.dumps(dict(span.attributes), default=str)
        assert KEY not in text
        assert "S00021" not in text  # a filter value from the arguments


def test_without_a_provider_nothing_is_recorded_and_audit_has_no_trace_id():
    tracing.use_provider(None)
    audit = MemoryAuditSink()

    search(audit)

    assert audit.events[0].trace_id is None


@pytest.mark.parametrize("mode", ["none", "", None])
def test_tracing_is_off_unless_asked(mode):
    assert tracing.configure(mode) is None


def test_console_tracing_can_be_switched_on():
    provider = tracing.configure("console")
    try:
        assert isinstance(provider, TracerProvider)
    finally:
        tracing.use_provider(None)


def test_unknown_modes_are_refused():
    with pytest.raises(ValueError, match="GATEWAY_TRACES"):
        tracing.configure("loud")
