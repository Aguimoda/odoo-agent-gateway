"""M7 acceptance: web sessions against the real Odoo and PostgreSQL (ADR 0018).

The browser side (the React app driving these endpoints) is in tests/e2e. Here the HTTP
contract is checked directly: the cookie, where it works, where it does not, and that the
Odoo key is never sent back nor stored in clear.
"""

import os
from pathlib import Path

import anyio
import asyncpg
import pytest
from starlette.testclient import TestClient

from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.secretbox import new_master_key
from odoo_agent_gateway.web_sessions import COOKIE_NAME, hash_id

pytestmark = pytest.mark.integration

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"
BASE = "http://127.0.0.1:8000"
SAME_SITE = {"origin": BASE}


def missing(reason: str):
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def demo() -> dict[str, str]:
    if not KEYS_FILE.exists():
        missing("Demo data missing: run scripts/demo/setup_demo.py first.")
    lines = KEYS_FILE.read_text(encoding="utf-8").splitlines()
    values = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    if "DEMO_CARMEN_API_KEY" not in values:
        missing("Demo data predates M6: run scripts/demo/setup_demo.py again.")
    return values


@pytest.fixture(scope="module")
def gateway(demo):
    settings = Settings(
        odoo_url=demo["ODOO_URL"],
        odoo_db=demo["ODOO_DB"],
        database_url=demo["GATEWAY_DATABASE_URL"],
        rate_limit_per_minute=1000,
        model_cache=os.environ.get("GATEWAY_MODEL_CACHE", ".cache/models"),
        secret_keys=new_master_key(),
    )
    with TestClient(create_app(settings), base_url=BASE) as client:
        yield client


@pytest.fixture
def browser(gateway):
    """An empty cookie jar per test, like a new browser."""
    gateway.cookies.clear()
    yield gateway
    gateway.cookies.clear()


def sign_in(client, demo, who: str):
    return client.post(
        "/session",
        json={
            "login": demo[f"DEMO_{who.upper()}_LOGIN"],
            "api_key": demo[f"DEMO_{who.upper()}_API_KEY"],
        },
        headers=SAME_SITE,
    )


def db(demo, query: str, *args):
    async def run():
        connection = await asyncpg.connect(demo["GATEWAY_DATABASE_URL"])
        try:
            return await connection.fetch(query, *args)
        finally:
            await connection.close()

    return anyio.run(run)


def test_the_key_stays_on_the_server(browser, demo):
    """Scenario: la clave no llega al navegador."""
    key = demo["DEMO_ANA_API_KEY"]
    response = sign_in(browser, demo, "ana")
    assert response.status_code == 200
    assert response.json()["login"] == demo["DEMO_ANA_LOGIN"]
    assert response.json()["is_admin"] is False
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert key not in response.text

    token = browser.cookies[COOKIE_NAME]
    (row,) = db(
        demo, "select key_encrypted, login from web_sessions where id_hash = $1", hash_id(token)
    )
    assert row["login"] == demo["DEMO_ANA_LOGIN"]
    assert key.encode() not in bytes(row["key_encrypted"])
    assert not db(demo, "select 1 from web_sessions where id_hash = $1", token.encode())

    for path in ("/session", "/agent/conversations", "/approvals/mine"):
        answer = browser.get(path)
        assert answer.status_code == 200, (path, answer.text)
        assert key not in answer.text
    assert not db(demo, "select 1 from audit_log where arguments::text like $1", f"%{key}%")


def test_a_wrong_key_creates_no_session(browser, demo):
    """Scenario: clave equivocada."""
    before = db(demo, "select count(*) as n from web_sessions")[0]["n"]
    response = browser.post(
        "/session",
        json={"login": demo["DEMO_ANA_LOGIN"], "api_key": "not-the-right-key"},
        headers=SAME_SITE,
    )
    assert response.status_code == 401
    assert COOKIE_NAME not in browser.cookies
    assert db(demo, "select count(*) as n from web_sessions")[0]["n"] <= before


def test_another_site_cannot_act_with_the_cookie(browser, demo):
    """Scenario: otra web no puede actuar en nombre de Ana."""
    sign_in(browser, demo, "ana")
    for headers in ({"origin": "https://evil.example"}, {}):
        response = browser.post("/agent/conversations", json={}, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"] == "forbidden"
    assert browser.post("/agent/conversations", json={}, headers=SAME_SITE).status_code == 200


def test_the_cookie_never_opens_mcp(browser, demo):
    sign_in(browser, demo, "ana")
    response = browser.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "my_permissions", "arguments": {}},
        },
        headers={"accept": "application/json, text/event-stream", **SAME_SITE},
    )
    assert "unauthenticated" in response.text


def test_signing_out_ends_the_session(browser, demo):
    """Scenario: salir."""
    sign_in(browser, demo, "ana")
    token = browser.cookies[COOKIE_NAME]
    assert browser.delete("/session", headers=SAME_SITE).json() == {"signed_out": True}
    assert not db(demo, "select 1 from web_sessions where id_hash = $1", hash_id(token))
    browser.cookies.set(COOKIE_NAME, token)  # even if the old cookie were kept
    assert browser.get("/session").status_code == 401


def test_the_admin_panel_is_decided_by_odoo(browser, demo):
    """Scenario: el panel solo para administradores."""
    sign_in(browser, demo, "ana")
    assert browser.get("/admin/providers").status_code == 403
    browser.delete("/session", headers=SAME_SITE)

    assert sign_in(browser, demo, "carmen").json()["is_admin"] is True
    assert browser.get("/admin/providers").status_code == 200
    settings = browser.get("/admin/settings").json()
    assert "search_knowledge" in settings["tools"] and "propose_change" in settings["tools"]
