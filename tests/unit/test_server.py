import json

import httpx2
import pytest
from mcp.client.client import Client
from starlette.testclient import TestClient

from odoo_agent_gateway.app import create_app
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
    server = build_mcp_server(SETTINGS, FakeOdoo().client)

    async with Client(server) as client:
        tools = (await client.list_tools()).tools

    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    assert all(tool.description and len(tool.description) > 40 for tool in tools)


@pytest.mark.anyio
async def test_calls_without_credentials_are_unauthenticated():
    odoo = FakeOdoo()
    server = build_mcp_server(SETTINGS, odoo.client)

    async with Client(server) as client:
        result = await client.call_tool("search_records", {"model": "sale.order"})

    assert result.is_error
    assert "unauthenticated" in result.content[0].text
    assert odoo.requests == []


# --- over HTTP, as a real MCP client would call it ----------------------------------------


def test_a_tool_call_reaches_odoo_with_the_callers_own_key():
    odoo = FakeOdoo()
    app = create_app(SETTINGS, http_client_factory=odoo.client)

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
    app = create_app(SETTINGS, http_client_factory=odoo.client)

    with TestClient(app, base_url=LOCAL) as test_client:
        result = call_tool(test_client, "search_records", {"model": "sale.order"}, headers)

    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "unauthenticated" in text
    assert ANA_KEY not in text and "made-up-key" not in text


def test_guardrail_errors_come_back_as_invalid_request():
    app = create_app(SETTINGS, http_client_factory=FakeOdoo().client)

    with TestClient(app, base_url=LOCAL) as test_client:
        result = call_tool(test_client, "search_records", {"model": "hr.employee"}, ana_headers())

    assert result["isError"] is True
    assert "invalid_request" in result["content"][0]["text"]


def test_requests_with_an_unexpected_host_header_are_refused():
    app = create_app(SETTINGS, http_client_factory=FakeOdoo().client)

    with TestClient(app, base_url="http://evil.example") as test_client:
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"accept": "application/json, text/event-stream", **ana_headers()},
        )

    assert response.status_code == 421


def test_health_still_answers_next_to_mcp():
    app = create_app(SETTINGS, http_client_factory=FakeOdoo().client)

    with TestClient(app, base_url=LOCAL) as test_client:
        assert test_client.get("/health").json()["status"] == "ok"
