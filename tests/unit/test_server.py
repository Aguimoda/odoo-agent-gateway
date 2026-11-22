import json

import httpx2
import pytest
from mcp.client.client import Client
from starlette.testclient import TestClient

from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.audit import MemoryAuditSink
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.server import build_mcp_server

ANA_KEY = "ana-real-key-0123456789"
SETTINGS = Settings(odoo_url="http://odoo.test", odoo_db="demo")
LOCAL = "http://127.0.0.1:8000"
EXPECTED_TOOLS = {
    "my_permissions",
    "list_models",
    "describe_model",
    "search_records",
    "read_record",
    "summarize_data",
}


class FakeOdoo:
    """A JSON-RPC Odoo that knows one user, Ana, and records every request it gets."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        params = json.loads(request.content)["params"]
        self.requests.append(params)
        if params["service"] == "common":
            _, login, key, _ = params["args"]
            result = 8 if (login, key) == ("ana", ANA_KEY) else False
        else:
            _, uid, key, model, method, args, kwargs = params["args"]
            assert (uid, key) == (8, ANA_KEY), "object calls must use Ana's own credentials"
            result = [{"id": 21, "display_name": "S00021"}] if method == "search_read" else None
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": None, "result": result})

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler))


def rpc(test_client: TestClient, method: str, params: dict, headers: dict) -> dict:
    base = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = test_client.post("/mcp", json=body, headers={**base, **headers})
    assert response.status_code == 200, response.text
    return response.json()


def call_tool(test_client: TestClient, name: str, arguments: dict, headers: dict) -> dict:
    init = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "tests", "version": "0"},
    }
    rpc(test_client, "initialize", init, headers)
    return rpc(test_client, "tools/call", {"name": name, "arguments": arguments}, headers)["result"]


def ana_headers(key: str = ANA_KEY) -> dict:
    return {"x-odoo-login": "ana", "authorization": f"Bearer {key}"}


# --- tool catalogue (in process) ----------------------------------------------------------


@pytest.mark.anyio
async def test_exposes_exactly_the_six_read_tools_with_descriptions():
    server = build_mcp_server(SETTINGS, FakeOdoo().client, audit=MemoryAuditSink())

    async with Client(server) as client:
        tools = (await client.list_tools()).tools

    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    assert all(tool.description and len(tool.description) > 40 for tool in tools)


@pytest.mark.anyio
async def test_calls_without_credentials_are_unauthenticated():
    odoo = FakeOdoo()
    server = build_mcp_server(SETTINGS, odoo.client, audit=MemoryAuditSink())

    async with Client(server) as client:
        result = await client.call_tool("search_records", {"model": "sale.order"})

    assert result.is_error
    assert "unauthenticated" in result.content[0].text
    assert odoo.requests == []


# --- over HTTP, as a real MCP client would call it ----------------------------------------


def test_a_tool_call_reaches_odoo_with_the_callers_own_key():
    odoo = FakeOdoo()
    app = create_app(SETTINGS, audit_sink=MemoryAuditSink(), http_client_factory=odoo.client)

    with TestClient(app, base_url=LOCAL) as test_client:
        result = call_tool(test_client, "search_records", {"model": "sale.order"}, ana_headers())

    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["records"] == [{"id": 21, "display_name": "S00021"}]
    assert odoo.requests[0]["args"][1:3] == ["ana", ANA_KEY]


@pytest.mark.parametrize(
    "headers",
    [
        ana_headers("made-up-key"),
        {"x-odoo-login": "ana", "authorization": f"Basic {ANA_KEY}"},
        {"authorization": f"Bearer {ANA_KEY}"},
        {},
    ],
)
def test_bad_or_missing_credentials_are_unauthenticated_and_never_echoed(headers):
    odoo = FakeOdoo()
    app = create_app(SETTINGS, audit_sink=MemoryAuditSink(), http_client_factory=odoo.client)

    with TestClient(app, base_url=LOCAL) as test_client:
        result = call_tool(test_client, "search_records", {"model": "sale.order"}, headers)

    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "unauthenticated" in text
    assert ANA_KEY not in text and "made-up-key" not in text


def test_guardrail_errors_come_back_as_invalid_request():
    app = create_app(SETTINGS, audit_sink=MemoryAuditSink(), http_client_factory=FakeOdoo().client)

    with TestClient(app, base_url=LOCAL) as test_client:
        result = call_tool(test_client, "search_records", {"model": "hr.employee"}, ana_headers())

    assert result["isError"] is True
    assert "invalid_request" in result["content"][0]["text"]


def test_requests_with_an_unexpected_host_header_are_refused():
    app = create_app(SETTINGS, audit_sink=MemoryAuditSink(), http_client_factory=FakeOdoo().client)

    with TestClient(app, base_url="http://evil.example") as test_client:
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"accept": "application/json, text/event-stream", **ana_headers()},
        )

    assert response.status_code == 421


def test_health_still_answers_next_to_mcp():
    app = create_app(SETTINGS, audit_sink=MemoryAuditSink(), http_client_factory=FakeOdoo().client)

    with TestClient(app, base_url=LOCAL) as test_client:
        assert test_client.get("/health").json()["status"] == "ok"


# --- audit log (ADR 0008) and rate limit (ADR 0009) ---------------------------------------


def make_app(audit=None, **settings):
    odoo = FakeOdoo()
    audit = audit if audit is not None else MemoryAuditSink()
    app_settings = Settings(odoo_url="http://odoo.test", odoo_db="demo", **settings)
    return create_app(app_settings, audit_sink=audit, http_client_factory=odoo.client), odoo, audit


def test_a_successful_call_is_audited_with_who_what_and_how_long():
    app, _, audit = make_app()

    with TestClient(app, base_url=LOCAL) as test_client:
        call_tool(test_client, "search_records", {"model": "sale.order", "limit": 5}, ana_headers())

    (event,) = audit.events
    assert (event.login, event.odoo_uid, event.tool) == ("ana", 8, "search_records")
    assert event.arguments == {"model": "sale.order", "limit": 5}
    assert event.outcome == "ok"
    assert event.result_count == 1
    assert event.duration_ms >= 0
    assert event.request_id


def test_a_failed_login_is_audited_without_a_user_id_or_the_key():
    app, _, audit = make_app()

    with TestClient(app, base_url=LOCAL) as test_client:
        call_tool(test_client, "list_models", {}, ana_headers("made-up-key"))

    (event,) = audit.events
    assert (event.login, event.odoo_uid, event.outcome) == ("ana", None, "unauthenticated")
    assert "made-up-key" not in repr(event)
    assert ANA_KEY not in repr(event)


def test_guardrail_errors_are_audited_with_their_code():
    app, _, audit = make_app()

    with TestClient(app, base_url=LOCAL) as test_client:
        call_tool(test_client, "search_records", {"model": "hr.employee"}, ana_headers())

    assert audit.events[0].outcome == "invalid_request"


def test_no_audit_means_no_data():
    app, odoo, _ = make_app(audit=MemoryAuditSink(available=False))

    with TestClient(app, base_url=LOCAL) as test_client:
        result = call_tool(test_client, "search_records", {"model": "sale.order"}, ana_headers())

    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "audit_unavailable" in text
    assert "S00021" not in text


def test_calls_over_the_limit_are_refused_before_reaching_odoo():
    app, odoo, audit = make_app(rate_limit_per_minute=2)

    with TestClient(app, base_url=LOCAL) as test_client:
        results = [call_tool(test_client, "list_models", {}, ana_headers()) for _ in range(3)]
        other = call_tool(test_client, "list_models", {}, {"x-odoo-login": "luis"})

    assert [r["isError"] for r in results] == [False, False, True]
    assert "rate_limited" in results[2]["content"][0]["text"]
    logins_sent_to_odoo = [r["args"][1] for r in odoo.requests if r["service"] == "common"]
    assert logins_sent_to_odoo == ["ana", "ana"]
    assert audit.events[2].outcome == "rate_limited"
    assert "rate_limited" not in other["content"][0]["text"]  # luis has his own budget


def test_the_app_refuses_to_start_without_an_audit_database():
    with pytest.raises(ValueError, match="GATEWAY_DATABASE_URL"):
        create_app(SETTINGS, http_client_factory=FakeOdoo().client)
