"""M1 acceptance scenarios against the real Odoo of the Docker stack.

Run with:  pytest -m integration
Needs `docker compose up -d` and `python scripts/demo/setup_demo.py` first; the demo users'
credentials are read from the git-ignored `.env.demo-keys`. The gateway is exercised over
MCP HTTP exactly as a client would call it.
"""

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.config import Settings

pytestmark = pytest.mark.integration

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"


def load_demo() -> dict[str, str]:
    if not KEYS_FILE.exists():
        pytest.skip("Demo data missing: run scripts/demo/setup_demo.py first.")
    lines = KEYS_FILE.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


@pytest.fixture(scope="module")
def demo() -> dict[str, str]:
    return load_demo()


@pytest.fixture(scope="module")
def gateway(demo):
    settings = Settings(odoo_url=demo["ODOO_URL"], odoo_db=demo["ODOO_DB"])
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
        yield client


def call(gateway: TestClient, tool: str, arguments: dict, login: str | None, key: str | None):
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    if login:
        headers["x-odoo-login"] = login
    if key:
        headers["authorization"] = f"Bearer {key}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call"}
    body["params"] = {"name": tool, "arguments": arguments}
    result = gateway.post("/mcp", json=body, headers=headers).json()["result"]
    text = result["content"][0]["text"]
    return (True, text) if result["isError"] else (False, json.loads(text))


def as_user(demo, who: str) -> tuple[str, str]:
    return demo[f"DEMO_{who.upper()}_LOGIN"], demo[f"DEMO_{who.upper()}_API_KEY"]


def order_ids(demo, who: str) -> set[int]:
    return {int(value) for value in demo[f"DEMO_{who.upper()}_ORDER_IDS"].split(",")}


DEMO_ORDERS = {"model": "sale.order", "domain": [["client_order_ref", "=like", "DEMO-%"]]}


def test_ana_only_sees_her_own_orders(gateway, demo):
    error, result = call(
        gateway, "search_records", {**DEMO_ORDERS, "fields": ["user_id"]}, *as_user(demo, "ana")
    )

    assert not error
    ids = {record["id"] for record in result["records"]}
    assert ids == order_ids(demo, "ana")
    assert not ids & order_ids(demo, "luis")
    assert {record["user_id"][1] for record in result["records"]} == {"Ana (Sales)"}


def test_ana_cannot_read_an_order_of_luis_even_knowing_its_id(gateway, demo):
    luis_order = min(order_ids(demo, "luis"))

    error, text = call(
        gateway,
        "read_record",
        {"model": "sale.order", "record_id": luis_order, "fields": ["name", "amount_total"]},
        *as_user(demo, "ana"),
    )

    assert error
    assert "forbidden" in text
    assert "S000" not in text  # no order reference leaks through the error


def test_luis_sees_the_orders_of_both(gateway, demo):
    error, result = call(gateway, "search_records", DEMO_ORDERS, *as_user(demo, "luis"))

    assert not error
    ids = {record["id"] for record in result["records"]}
    assert order_ids(demo, "ana") | order_ids(demo, "luis") <= ids


def test_a_made_up_api_key_is_rejected(gateway, demo):
    error, text = call(gateway, "list_models", {}, demo["DEMO_ANA_LOGIN"], "made-up-key-123")

    assert error
    assert "unauthenticated" in text


def test_no_credentials_means_no_data(gateway):
    error, text = call(gateway, "search_records", {"model": "sale.order"}, None, None)

    assert error
    assert "unauthenticated" in text


def test_models_outside_the_allowlist_are_refused(gateway, demo):
    error, text = call(gateway, "search_records", {"model": "res.users"}, *as_user(demo, "luis"))

    assert error
    assert "invalid_request" in text


def test_summaries_respect_permissions(gateway, demo):
    error, result = call(
        gateway,
        "summarize_data",
        {**DEMO_ORDERS, "group_by": ["user_id"], "aggregates": ["amount_total:sum"]},
        *as_user(demo, "ana"),
    )

    assert not error
    assert [group["user_id"][1] for group in result["groups"]] == ["Ana (Sales)"]
    assert result["groups"][0]["count"] == len(order_ids(demo, "ana"))


def test_large_searches_are_capped_at_fifty(gateway, demo):
    error, result = call(
        gateway, "search_records", {"model": "res.partner", "limit": 500}, *as_user(demo, "luis")
    )

    assert not error
    assert result["returned"] <= 50


def test_my_permissions_reflects_odoo_rights(gateway, demo):
    _, ana = call(gateway, "my_permissions", {}, *as_user(demo, "ana"))
    _, luis = call(gateway, "my_permissions", {}, *as_user(demo, "luis"))

    assert ana["user"]["login"] == "ana"
    assert ana["models"]["sale.order"]["read"] is True
    assert ana["models"]["sale.order"]["unlink"] is False
    assert luis["models"]["sale.order"]["unlink"] is True
