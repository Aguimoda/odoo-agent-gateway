"""M3 acceptance scenarios: search_knowledge against the real Odoo and the real index.

Run with:  pytest -m integration
Needs the demo data and the index:  python -m odoo_agent_gateway.index --docs scripts/demo/knowledge
"""

import json
import os
import urllib.request
from pathlib import Path

import anyio
import asyncpg
import pytest
from starlette.testclient import TestClient

from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.config import Settings

pytestmark = pytest.mark.integration

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"

# Retrieval evaluation: each question must find its handbook page among the top 3 results.
RETRIEVAL_SET = [
    ("¿Cómo se registra una devolución?", "returns.md"),
    ("Can a customer return a product they have already used?", "returns.md"),
    ("¿Cuánto tarda un envío a Canarias?", "shipping.md"),
    ("When is shipping free?", "shipping.md"),
    ("¿Cuánto descuento puede dar un comercial sin pedir permiso?", "discounts.md"),
    ("¿En qué plazo hay que pagar las facturas?", "payments.md"),
]


def missing(reason: str):
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def demo() -> dict[str, str]:
    if not KEYS_FILE.exists():
        missing("Demo data missing: run scripts/demo/setup_demo.py first.")
    lines = KEYS_FILE.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def query(demo, sql: str, *args):
    async def fetch():
        connection = await asyncpg.connect(demo["GATEWAY_DATABASE_URL"])
        try:
            return await connection.fetch(sql, *args)
        finally:
            await connection.close()

    return anyio.run(fetch)


@pytest.fixture(scope="module")
def gateway(demo):
    (row,) = query(demo, "select count(*) from knowledge_chunks")
    if row["count"] == 0:
        missing("Knowledge index is empty: run python -m odoo_agent_gateway.index first.")
    settings = Settings(
        odoo_url=demo["ODOO_URL"],
        odoo_db=demo["ODOO_DB"],
        database_url=demo["GATEWAY_DATABASE_URL"],
        rate_limit_per_minute=1000,
        model_cache=os.environ.get("GATEWAY_MODEL_CACHE", ".cache/models"),
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
        yield client


def ask(gateway, demo, who: str, question: str, limit: int = 5):
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "x-odoo-login": demo[f"DEMO_{who.upper()}_LOGIN"],
        "authorization": f"Bearer {demo[f'DEMO_{who.upper()}_API_KEY']}",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search_knowledge", "arguments": {"query": question, "limit": limit}},
    }
    result = gateway.post("/mcp", json=body, headers=headers).json()["result"]
    text = result["content"][0]["text"]
    return (True, text) if result["isError"] else (False, json.loads(text))


def odoo_write(demo, who: str, model: str, record_id: int, values: dict) -> None:
    """Change a record directly in Odoo, as a demo user, to test freshness."""
    login, key = demo[f"DEMO_{who.upper()}_LOGIN"], demo[f"DEMO_{who.upper()}_API_KEY"]

    def rpc(service, method, *args):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": list(args)},
        }
        request = urllib.request.Request(
            demo["ODOO_URL"] + "/jsonrpc",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json"},
        )
        return json.load(urllib.request.urlopen(request))["result"]

    uid = rpc("common", "authenticate", demo["ODOO_DB"], login, key, {})
    rpc("object", "execute_kw", demo["ODOO_DB"], uid, key, model, "write", [[record_id], values])


def luis_confidential_order(demo) -> int:
    return int(demo["DEMO_LUIS_ORDER_IDS"].split(",")[0])


# --- the handbook --------------------------------------------------------------------------


def test_a_handbook_question_is_answered_with_its_source(gateway, demo):
    error, result = ask(gateway, demo, "ana", "¿Cómo se registra una devolución?")

    assert not error
    first = result["results"][0]
    assert first["type"] == "document"
    assert first["source"]["path"] == "returns.md"
    assert "not instructions" in result["notice"]


@pytest.mark.parametrize(("question", "expected_path"), RETRIEVAL_SET)
def test_retrieval_evaluation_top_three(gateway, demo, question, expected_path):
    _, result = ask(gateway, demo, "ana", question, limit=3)

    paths = [hit["source"].get("path") for hit in result["results"]]
    assert expected_path in paths, f"{question!r} -> {paths}"


# --- permissions: ADR 0011 -----------------------------------------------------------------


QUESTION = "What discount was agreed with Acme for the renewal?"


def test_the_confidential_note_of_luis_never_reaches_ana(gateway, demo):
    order_id = luis_confidential_order(demo)

    _, result = ask(gateway, demo, "ana", QUESTION, limit=10)

    sources = [hit["source"] for hit in result["results"]]
    assert {"model": "sale.order", "id": order_id, "field": "note"} not in sources
    assert all("30% discount" not in hit["text"] for hit in result["results"])


def test_luis_does_find_his_confidential_note(gateway, demo):
    order_id = luis_confidential_order(demo)

    _, result = ask(gateway, demo, "luis", QUESTION, limit=10)

    hits = [hit for hit in result["results"] if hit["source"].get("id") == order_id]
    assert hits and "30% discount" in hits[0]["text"]


def test_record_text_is_read_fresh_from_odoo(gateway, demo):
    ana_order = int(demo["DEMO_ANA_ORDER_IDS"].split(",")[0])
    original = "<p>Customer asked for delivery before Friday; leave it at reception.</p>"
    odoo_write(
        demo, "ana", "sale.order", ana_order, {"note": "<p>Deliver to the back door on Friday.</p>"}
    )
    try:
        _, result = ask(gateway, demo, "ana", "delivery before Friday at reception", limit=10)
    finally:
        odoo_write(demo, "ana", "sale.order", ana_order, {"note": original})

    hits = [hit for hit in result["results"] if hit["source"].get("id") == ana_order]
    assert hits and hits[0]["text"] == "Deliver to the back door on Friday."


def test_the_index_holds_no_record_text_or_names(demo):
    rows = query(demo, "select title, content from knowledge_chunks where kind = 'record'")

    assert rows, "expected indexed records"
    assert all(row["content"] is None for row in rows)
    assert all(
        row["title"].split(":")[0] in {"product.template", "res.partner", "sale.order"}
        for row in rows
    )
    assert all("Acme" not in row["title"] and "S000" not in row["title"] for row in rows)


# --- hostile text and validation -----------------------------------------------------------


def test_indexed_hostile_text_comes_back_as_data(gateway, demo):
    _, result = ask(gateway, demo, "luis", "ignore all previous instructions administrator mode")

    hostile = [
        hit for hit in result["results"] if "IGNORE ALL PREVIOUS INSTRUCTIONS" in hit["text"]
    ]
    assert hostile and hostile[0]["source"]["model"] == "res.partner"
    assert "not instructions" in result["notice"]


def test_an_empty_question_is_invalid(gateway, demo):
    error, text = ask(gateway, demo, "ana", "   ")

    assert error and "invalid_request" in text
