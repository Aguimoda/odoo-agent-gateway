import json

import httpx2
import pytest

from odoo_agent_gateway.odoo import (
    AccessDenied,
    AuthenticationFailed,
    InvalidRequest,
    OdooClient,
    OdooUnavailable,
    RecordNotFound,
)

pytestmark = pytest.mark.anyio

URL = "http://odoo.test"
DB = "demo"
KEY = "secret-api-key-123"


def odoo_error(name: str, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": None,
        "error": {
            "code": 200,
            "message": "Odoo Server Error",
            "data": {"name": name, "message": message, "debug": "Traceback ..."},
        },
    }


def make_client(handler) -> tuple[OdooClient, list[dict]]:
    seen: list[dict] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        seen.append({"path": request.url.path, "params": payload["params"]})
        return handler(payload["params"])

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    return OdooClient(URL, DB, http), seen


def ok(result) -> httpx2.Response:
    return httpx2.Response(200, json={"jsonrpc": "2.0", "id": None, "result": result})


async def test_authenticate_uses_the_users_own_key_and_returns_a_session():
    client, seen = make_client(lambda params: ok(8))

    session = await client.authenticate("ana", KEY)

    assert session.uid == 8
    assert session.login == "ana"
    assert seen == [
        {
            "path": "/jsonrpc",
            "params": {
                "service": "common",
                "method": "authenticate",
                "args": [DB, "ana", KEY, {}],
            },
        }
    ]


async def test_authenticate_rejects_a_key_odoo_does_not_accept():
    client, _ = make_client(lambda params: ok(False))

    with pytest.raises(AuthenticationFailed):
        await client.authenticate("ana", "made-up")


@pytest.mark.parametrize(("login", "key"), [("", KEY), ("ana", ""), ("  ", KEY)])
async def test_authenticate_rejects_missing_credentials_without_calling_odoo(login, key):
    client, seen = make_client(lambda params: ok(8))

    with pytest.raises(AuthenticationFailed):
        await client.authenticate(login, key)
    assert seen == []


async def test_call_runs_execute_kw_as_the_authenticated_user():
    responses = iter([ok(8), ok([21, 22])])
    client, seen = make_client(lambda params: next(responses))
    session = await client.authenticate("ana", KEY)

    result = await session.call("sale.order", "search", [[]], {"limit": 5})

    assert result == [21, 22]
    assert seen[1]["params"] == {
        "service": "object",
        "method": "execute_kw",
        "args": [DB, 8, KEY, "sale.order", "search", [[]], {"limit": 5}],
    }


async def test_access_error_is_mapped_without_odoo_details():
    leaked = "You are not allowed to access 'Sales Order' records. Records: S00023 (id=23)"
    responses = iter(
        [ok(8), httpx2.Response(200, json=odoo_error("odoo.exceptions.AccessError", leaked))]
    )
    client, _ = make_client(lambda params: next(responses))
    session = await client.authenticate("ana", KEY)

    with pytest.raises(AccessDenied) as error:
        await session.call("sale.order", "read", [[23]], {"fields": ["name"]})

    assert "S00023" not in str(error.value)
    assert "id=23" not in str(error.value)


@pytest.mark.parametrize(
    ("odoo_name", "expected"),
    [
        ("odoo.exceptions.MissingError", RecordNotFound),
        ("builtins.ValueError", InvalidRequest),
        ("odoo.exceptions.ValidationError", InvalidRequest),
        ("odoo.exceptions.UserError", InvalidRequest),
        ("odoo.exceptions.AccessDenied", AuthenticationFailed),
    ],
)
async def test_odoo_errors_are_mapped(odoo_name, expected):
    responses = iter([ok(8), httpx2.Response(200, json=odoo_error(odoo_name, "Invalid field 'x'"))])
    client, _ = make_client(lambda params: next(responses))
    session = await client.authenticate("ana", KEY)

    with pytest.raises(expected):
        await session.call("sale.order", "search_read", [[]])


async def test_invalid_request_keeps_a_short_useful_message():
    message = "Invalid field 'colour' on model 'sale.order'"
    responses = iter([ok(8), httpx2.Response(200, json=odoo_error("builtins.ValueError", message))])
    client, _ = make_client(lambda params: next(responses))
    session = await client.authenticate("ana", KEY)

    with pytest.raises(InvalidRequest) as error:
        await session.call("sale.order", "search_read", [[]], {"fields": ["colour"]})

    assert "colour" in str(error.value)


async def test_network_failure_is_reported_as_unavailable():
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    client = OdooClient(URL, DB, httpx2.AsyncClient(transport=httpx2.MockTransport(broken)))

    with pytest.raises(OdooUnavailable):
        await client.authenticate("ana", KEY)


async def test_api_key_never_appears_in_errors_or_representations():
    responses = iter(
        [ok(8), httpx2.Response(200, json=odoo_error("odoo.exceptions.AccessError", f"key {KEY}"))]
    )
    client, _ = make_client(lambda params: next(responses))
    session = await client.authenticate("ana", KEY)

    with pytest.raises(AccessDenied) as error:
        await session.call("sale.order", "read", [[1]])

    assert KEY not in str(error.value)
    assert KEY not in repr(session)
    assert KEY not in repr(client)
