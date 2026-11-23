"""M6 acceptance: the admin API against the real Odoo and PostgreSQL (ADR 0015).

Odoo decides who administers (Carmen is in Settings; Ana and Luis are not), provider keys
are encrypted, write-only and never audited, and a stored key cannot follow a URL change.
"""

import json
import os
import uuid
from pathlib import Path

import anyio
import asyncpg
import httpx2
import pytest
from starlette.testclient import TestClient

from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.secretbox import new_master_key

pytestmark = pytest.mark.integration

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"
FAKE_PROVIDER_KEY = "fake-provider-key-" + uuid.uuid4().hex  # unique, so we can search for it


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


def fake_provider(request: httpx2.Request) -> httpx2.Response:
    if request.url.path.endswith("/models"):
        if request.headers.get("authorization") != f"Bearer {FAKE_PROVIDER_KEY}":
            return httpx2.Response(401, json={"error": {"message": "Invalid API Key"}})
        return httpx2.Response(200, json={"data": [{"id": "model-b"}, {"id": "model-a"}]})
    return httpx2.Response(404)


def settings_for(demo, **changes) -> Settings:
    values = dict(
        odoo_url=demo["ODOO_URL"],
        odoo_db=demo["ODOO_DB"],
        database_url=demo["GATEWAY_DATABASE_URL"],
        rate_limit_per_minute=1000,
        model_cache=os.environ.get("GATEWAY_MODEL_CACHE", ".cache/models"),
        secret_keys=new_master_key(),
    )
    values.update(changes)
    return Settings(**values)


@pytest.fixture(scope="module")
def gateway(demo):
    app = create_app(
        settings_for(demo),
        llm_http=httpx2.AsyncClient(transport=httpx2.MockTransport(fake_provider)),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


def headers(demo, who: str) -> dict[str, str]:
    return {
        "x-odoo-login": demo[f"DEMO_{who.upper()}_LOGIN"],
        "authorization": f"Bearer {demo[f'DEMO_{who.upper()}_API_KEY']}",
    }


def db(demo, query: str, *args):
    async def run():
        connection = await asyncpg.connect(demo["GATEWAY_DATABASE_URL"])
        try:
            return await connection.fetch(query, *args)
        finally:
            await connection.close()

    return anyio.run(run)


@pytest.fixture
def provider(gateway, demo):
    """A provider created by Carmen for one test, removed afterwards."""
    name = f"test-{uuid.uuid4().hex[:8]}"
    response = gateway.post(
        "/admin/providers",
        json={"name": name, "base_url": "https://llm.test/v1", "api_key": FAKE_PROVIDER_KEY},
        headers=headers(demo, "carmen"),
    )
    assert response.status_code == 200, response.text
    created = response.json()
    yield created
    gateway.delete(f"/admin/providers/{created['id']}", headers=headers(demo, "carmen"))


@pytest.mark.parametrize("who", ["ana", "luis"])
def test_only_odoo_administrators_administer(gateway, demo, who):
    """Scenario: solo administra quien Odoo dice."""
    response = gateway.get("/admin/providers", headers=headers(demo, who))
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    (row,) = db(
        demo,
        "select outcome from audit_log where tool = 'admin.providers' and login = $1 "
        "order by id desc limit 1",
        demo[f"DEMO_{who.upper()}_LOGIN"],
    )
    assert row["outcome"] == "forbidden"


def test_creating_a_provider_needs_an_administrator(gateway, demo):
    response = gateway.post(
        "/admin/providers",
        json={"name": "sneaky", "base_url": "https://llm.test/v1", "api_key": "x" * 20},
        headers=headers(demo, "luis"),
    )
    assert response.status_code == 403
    assert not db(demo, "select 1 from llm_providers where name = 'sneaky'")


def test_wrong_credentials_are_unauthenticated(gateway, demo):
    response = gateway.get(
        "/admin/providers",
        headers={"x-odoo-login": "carmen", "authorization": "Bearer not-the-key"},
    )
    assert response.status_code == 401


def test_the_key_never_comes_back(gateway, demo, provider):
    """Scenario: la clave no vuelve a salir."""
    assert provider["key_set"] is True
    assert FAKE_PROVIDER_KEY not in json.dumps(provider)
    listing = gateway.get("/admin/providers", headers=headers(demo, "carmen"))
    assert listing.status_code == 200
    assert FAKE_PROVIDER_KEY not in listing.text
    (stored,) = db(
        demo, "select api_key_encrypted from llm_providers where id = $1", provider["id"]
    )
    assert FAKE_PROVIDER_KEY.encode() not in bytes(stored["api_key_encrypted"])
    audited = db(
        demo,
        "select arguments::text as args from audit_log where tool like 'admin.%' "
        "and arguments::text like $1",
        f"%{provider['name']}%",
    )
    assert audited and all(FAKE_PROVIDER_KEY not in row["args"] for row in audited)
    assert any('"api_key": "***"' in row["args"] for row in audited)


def test_a_stored_key_does_not_follow_a_url_change(gateway, demo, provider):
    """Scenario: la clave no viaja a otra dirección."""
    url = f"/admin/providers/{provider['id']}"
    moved = gateway.patch(
        url, json={"base_url": "https://attacker.test/v1"}, headers=headers(demo, "carmen")
    )
    assert moved.status_code == 422
    with_key = gateway.patch(
        url,
        json={"base_url": "https://llm2.test/v1", "api_key": FAKE_PROVIDER_KEY},
        headers=headers(demo, "carmen"),
    )
    assert with_key.status_code == 200
    assert with_key.json()["base_url"] == "https://llm2.test/v1"


def test_plain_http_to_the_internet_is_refused(gateway, demo):
    response = gateway.post(
        "/admin/providers",
        json={"name": f"t-{uuid.uuid4().hex[:6]}", "base_url": "http://api.groq.com/openai/v1"},
        headers=headers(demo, "carmen"),
    )
    assert response.status_code == 422


def test_duplicate_names_conflict(gateway, demo, provider):
    response = gateway.post(
        "/admin/providers",
        json={"name": provider["name"], "base_url": "https://llm.test/v1"},
        headers=headers(demo, "carmen"),
    )
    assert response.status_code == 409


def test_models_test_connection_and_default(gateway, demo, provider):
    carmen = headers(demo, "carmen")
    tested = gateway.post(f"/admin/providers/{provider['id']}/test", headers=carmen)
    assert tested.json() == {"ok": True, "models": ["model-a", "model-b"]}

    added = gateway.post(
        f"/admin/providers/{provider['id']}/models",
        json={"name": "model-a", "label": "Model A", "is_default": True},
        headers=carmen,
    )
    assert added.status_code == 200
    (model,) = added.json()["models"]
    assert model["is_default"] and model["status"] == "ok"

    disabled = gateway.patch(
        f"/admin/models/{model['id']}", json={"enabled": False}, headers=carmen
    )
    assert disabled.json()["models"][0]["status"] == "disabled"
    assert gateway.delete(f"/admin/models/{model['id']}", headers=carmen).json()["models"] == []


def test_a_refused_key_marks_the_provider(gateway, demo, provider):
    carmen = headers(demo, "carmen")
    gateway.patch(
        f"/admin/providers/{provider['id']}", json={"api_key": "wrong-key-0000"}, headers=carmen
    )
    tested = gateway.post(f"/admin/providers/{provider['id']}/test", headers=carmen)
    assert tested.json()["ok"] is False and tested.json()["error"] == "auth_failed"
    listing = gateway.get("/admin/providers", headers=carmen).json()["providers"]
    (mine,) = [p for p in listing if p["id"] == provider["id"]]
    assert mine["status"] == "auth_failed"

    gateway.patch(
        f"/admin/providers/{provider['id']}", json={"api_key": FAKE_PROVIDER_KEY}, headers=carmen
    )
    listing = gateway.get("/admin/providers", headers=carmen).json()["providers"]
    (mine,) = [p for p in listing if p["id"] == provider["id"]]
    assert mine["status"] == "ok"  # a new key gets a new chance


def test_settings_round_trip(gateway, demo):
    carmen = headers(demo, "carmen")
    before = gateway.get("/admin/settings", headers=carmen).json()
    try:
        changed = gateway.patch(
            "/admin/settings",
            json={"retention_days": 45, "disabled_tools": ["propose_change"], "max_steps": 5},
            headers=carmen,
        )
        assert changed.status_code == 200
        assert changed.json()["retention_days"] == 45
        assert changed.json()["disabled_tools"] == ["propose_change"]
        assert changed.json()["updated_by"] == "carmen"
        assert gateway.patch("/admin/settings", json={}, headers=carmen).status_code == 422
        refused = gateway.patch("/admin/settings", json={"retention_days": 0}, headers=carmen)
        assert refused.status_code == 422
    finally:
        gateway.patch(
            "/admin/settings",
            json={k: before[k] for k in ("retention_days", "disabled_tools", "max_steps")},
            headers=carmen,
        )


def test_usage_summary_shape(gateway, demo):
    response = gateway.get("/admin/usage?days=7", headers=headers(demo, "carmen"))
    assert response.status_code == 200
    assert response.json()["days"] == 7 and isinstance(response.json()["usage"], list)


def test_without_master_keys_providers_are_unavailable(demo):
    app = create_app(settings_for(demo, secret_keys=None))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/admin/providers", headers=headers(demo, "carmen"))
    assert response.status_code == 503
    assert response.json()["error"] == "providers_unavailable"
