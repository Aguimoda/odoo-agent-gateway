"""M6 acceptance: the assistant against the real Odoo and PostgreSQL, with scripted providers.

The language model is the only fake: each provider host answers in a fixed way (good, rate
limited, wrong key, down). Everything else is real: Odoo permissions, the MCP endpoint
called in process, the audit log, conversations and provider health.
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
FAKE_PROVIDER_KEY = "fake-provider-key-for-tests-only"
ANSWER = "El plazo de envío es de 3 días laborables (shipping.md)."
CALLS: list[str] = []  # provider hosts called, in order


def missing(reason: str):
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def sse(*chunks) -> httpx2.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(
        200, content=body.encode(), headers={"content-type": "text/event-stream"}
    )


def fake_llm(request: httpx2.Request) -> httpx2.Response:
    host = request.url.host
    CALLS.append(host)
    if host == "limited.test":
        return httpx2.Response(429, headers={"retry-after": "40"}, text="requests per minute")
    if host == "badkey.test":
        return httpx2.Response(401, json={"error": {"message": "Invalid API Key"}})
    if host == "down.test":
        return httpx2.Response(503)
    messages = json.loads(request.content)["messages"]
    if messages[-1]["role"] == "tool":
        words = ANSWER.split(" ")
        chunks = [{"choices": [{"delta": {"content": w + " "}}]} for w in words[:-1]]
        chunks.append({"choices": [{"delta": {"content": words[-1]}}]})
        chunks.append(
            {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 50, "completion_tokens": 12}}
        )
        return sse(*chunks)
    call = {
        "index": 0,
        "id": "call-1",
        "type": "function",
        "function": {"name": "search_knowledge", "arguments": '{"query": "plazo de envío"}'},
    }
    return sse({"choices": [{"delta": {"tool_calls": [call]}}]})


@pytest.fixture(scope="module")
def demo() -> dict[str, str]:
    if not KEYS_FILE.exists():
        missing("Demo data missing: run scripts/demo/setup_demo.py first.")
    lines = KEYS_FILE.read_text(encoding="utf-8").splitlines()
    values = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    if "DEMO_CARMEN_API_KEY" not in values:
        missing("Demo data predates M6: run scripts/demo/setup_demo.py again.")
    return values


def headers(demo, who: str) -> dict[str, str]:
    return {
        "x-odoo-login": demo[f"DEMO_{who.upper()}_LOGIN"],
        "authorization": f"Bearer {demo[f'DEMO_{who.upper()}_API_KEY']}",
    }


@pytest.fixture(scope="module")
def gateway(demo):
    settings = Settings(
        odoo_url=demo["ODOO_URL"],
        odoo_db=demo["ODOO_DB"],
        database_url=demo["GATEWAY_DATABASE_URL"],
        rate_limit_per_minute=1000,
        model_cache=os.environ.get("GATEWAY_MODEL_CACHE", ".cache/models"),
        secret_keys=new_master_key(),
        agent_messages_per_minute=1000,
    )
    app = create_app(
        settings, llm_http=httpx2.AsyncClient(transport=httpx2.MockTransport(fake_llm))
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


@pytest.fixture(scope="module")
def models(gateway, demo):
    """Four providers with one model each; 'good' is the default. Removed afterwards."""
    carmen = headers(demo, "carmen")
    created, ids = [], {}
    suffix = uuid.uuid4().hex[:6]
    for host in ("good", "limited", "badkey", "down"):
        provider = gateway.post(
            "/admin/providers",
            json={
                "name": f"{host}-{suffix}",
                "base_url": f"https://{host}.test/v1",
                "api_key": FAKE_PROVIDER_KEY,
            },
            headers=carmen,
        ).json()
        created.append(provider["id"])
        view = gateway.post(
            f"/admin/providers/{provider['id']}/models",
            json={"name": f"{host}-model", "is_default": host == "good"},
            headers=carmen,
        ).json()
        ids[host] = view["models"][0]["id"]
    yield ids
    for provider_id in created:
        gateway.delete(f"/admin/providers/{provider_id}", headers=carmen)


def events(response) -> list[tuple[str, dict]]:
    parsed = []
    for block in response.text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


def new_conversation(gateway, demo, who="ana") -> str:
    response = gateway.post("/agent/conversations", json={}, headers=headers(demo, who))
    assert response.status_code == 200, response.text
    return response.json()["id"]


def send(gateway, demo, conversation, text, model_id=None, who="ana"):
    return gateway.post(
        f"/agent/conversations/{conversation}/messages",
        json={"content": text, "model_id": model_id},
        headers=headers(demo, who),
    )


def db(demo, query: str, *args):
    async def run():
        connection = await asyncpg.connect(demo["GATEWAY_DATABASE_URL"])
        try:
            return await connection.fetch(query, *args)
        finally:
            await connection.close()

    return anyio.run(run)


def test_models_lists_the_default(gateway, demo, models):
    response = gateway.get("/agent/models", headers=headers(demo, "ana"))
    assert response.status_code == 200
    assert response.json()["default"] == models["good"]


def test_streamed_answer_with_tools_run_as_the_person(gateway, demo, models):
    """Scenario: respuesta en streaming con las herramientas de la persona."""
    conversation = new_conversation(gateway, demo)
    response = send(gateway, demo, conversation, "¿Cuál es el plazo de envío?")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    got = events(response)
    kinds = [kind for kind, _ in got]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert kinds.count("token") == len(ANSWER.split(" "))
    tool_result = dict(got)["tool_result"]
    assert tool_result["name"] == "search_knowledge" and tool_result["ok"] is True
    assert "".join(d["text"] for k, d in got if k == "token") == ANSWER

    # The tool ran as Ana, through MCP, and was audited like any other call.
    (audit,) = db(
        demo,
        "select login, outcome from audit_log where tool = 'search_knowledge' "
        "and arguments->>'query' = 'plazo de envío' and login = $1 order by id desc limit 1",
        demo["DEMO_ANA_LOGIN"],
    )
    assert audit["outcome"] == "ok"
    assert db(
        demo,
        "select 1 from audit_log where tool = 'agent.message' and "
        "arguments->>'conversation_id' = $1",
        conversation,
    )

    # Stored: question, answer, tool name and arguments. Not stored: what the tool returned.
    stored = gateway.get(f"/agent/conversations/{conversation}", headers=headers(demo, "ana"))
    messages = stored.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == ANSWER
    (tool,) = messages[1]["tools"]
    assert set(tool) == {"name", "arguments", "ok", "count"}

    usage = gateway.get("/admin/usage", headers=headers(demo, "carmen")).json()["usage"]
    assert any(row["model"] == "good-model" and row["prompt_tokens"] >= 50 for row in usage)


def test_free_tier_limit_offers_other_models_and_does_not_switch(gateway, demo, models):
    """Scenario: límite del plan gratuito."""
    conversation = new_conversation(gateway, demo)
    CALLS.clear()
    got = events(send(gateway, demo, conversation, "Hola", model_id=models["limited"]))
    kind, error = got[-1]
    assert kind == "error" and error["kind"] == "rate_limited"
    assert error["retry_after"] == 40
    alternative_ids = {m["id"] for m in error["alternatives"]}
    assert models["good"] in alternative_ids and models["limited"] not in alternative_ids
    assert set(CALLS) == {"limited.test"}  # nothing was sent anywhere else

    retried = events(
        gateway.post(
            f"/agent/conversations/{conversation}/retry",
            json={"model_id": models["good"]},
            headers=headers(demo, "ana"),
        )
    )
    assert retried[-1][0] == "done"
    messages = gateway.get(
        f"/agent/conversations/{conversation}", headers=headers(demo, "ana")
    ).json()["messages"]
    assert [(m["role"], m["status"]) for m in messages] == [
        ("user", "complete"),
        ("assistant", "error"),
        ("assistant", "complete"),
    ]


def test_a_refused_key_takes_the_provider_out_until_replaced(gateway, demo, models):
    """Scenario: clave caducada."""
    conversation = new_conversation(gateway, demo)
    got = events(send(gateway, demo, conversation, "Hola", model_id=models["badkey"]))
    assert got[-1][1]["kind"] == "auth_failed"
    again = events(send(gateway, demo, conversation, "Hola", model_id=models["badkey"]))
    assert again[-1][1]["kind"] == "auth_failed"  # refused before calling the provider
    providers = gateway.get("/admin/providers", headers=headers(demo, "carmen")).json()
    (badkey,) = [p for p in providers["providers"] if p["base_url"] == "https://badkey.test/v1"]
    assert badkey["status"] == "auth_failed"


def test_circuit_breaker_stops_calling_a_provider_that_is_down(gateway, demo, models):
    """Scenario: proveedor caído."""
    conversation = new_conversation(gateway, demo)
    for _ in range(3):
        got = events(send(gateway, demo, conversation, "Hola", model_id=models["down"]))
        assert got[-1][1]["kind"] == "provider_unavailable"
    CALLS.clear()
    got = events(send(gateway, demo, conversation, "Hola", model_id=models["down"]))
    assert got[-1][1]["kind"] == "provider_unavailable"
    assert CALLS == []  # the breaker is open: the provider was not called at all


def test_conversations_are_private_and_deletable(gateway, demo, models):
    """Scenario: conversaciones privadas."""
    conversation = new_conversation(gateway, demo)
    for path in (f"/agent/conversations/{conversation}",):
        assert gateway.get(path, headers=headers(demo, "luis")).status_code == 404
    assert send(gateway, demo, conversation, "Hola", who="luis").status_code == 404
    assert (
        gateway.delete(
            f"/agent/conversations/{conversation}", headers=headers(demo, "luis")
        ).status_code
        == 404
    )
    deleted = gateway.delete(f"/agent/conversations/{conversation}", headers=headers(demo, "ana"))
    assert deleted.status_code == 200
    assert (
        gateway.get(
            f"/agent/conversations/{conversation}", headers=headers(demo, "ana")
        ).status_code
        == 404
    )


def test_no_stream_without_valid_credentials(gateway, demo, models):
    conversation = new_conversation(gateway, demo)
    response = gateway.post(
        f"/agent/conversations/{conversation}/messages",
        json={"content": "Hola"},
        headers={"x-odoo-login": "ana", "authorization": "Bearer wrong"},
    )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
