"""Web sessions (ADR 0018): the key stays on the server, the cookie is the only handle.

The rules are tested with an in-memory storage; the PostgreSQL storage and the whole flow
against real Odoo are in tests/integration/test_live_web.py.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import anyio
import httpx2
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from odoo_agent_gateway.audit import MemoryAuditSink
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.gateway import Gateway, OdooProvider
from odoo_agent_gateway.ratelimit import RateLimiter
from odoo_agent_gateway.secretbox import SecretBox, new_master_key
from odoo_agent_gateway.web_app import build_session_router
from odoo_agent_gateway.web_sessions import (
    COOKIE_NAME,
    WebSessionMiddleware,
    WebSessions,
    cookie_value,
    hash_id,
    origin_allowed,
)

KEY = "fixture-not-a-real-credential-ana"
BOX = SecretBox.from_env(new_master_key())
HOSTS = ("127.0.0.1:*", "localhost:*")
ORIGINS = ("http://127.0.0.1:*", "http://localhost:*")


class MemoryStorage:
    def __init__(self) -> None:
        self.rows: dict[bytes, object] = {}

    async def insert(self, row) -> None:
        self.rows[row.id_hash] = row

    async def get(self, id_hash):
        return self.rows.get(id_hash)

    async def touch(self, id_hash, at) -> None:
        self.rows[id_hash] = replace(self.rows[id_hash], last_seen_at=at)

    async def delete(self, id_hash) -> None:
        self.rows.pop(id_hash, None)

    async def purge(self, now, idle_before) -> int:
        old = [
            k for k, r in self.rows.items() if r.expires_at <= now or r.last_seen_at <= idle_before
        ]
        for key in old:
            del self.rows[key]
        return len(old)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def sessions(clock=None, storage=None) -> WebSessions:
    return WebSessions(storage or MemoryStorage(), BOX, clock=clock or Clock())


# -- the rules ---------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_session_resolves_to_the_person_and_stores_no_key_in_clear():
    storage = MemoryStorage()
    web = sessions(storage=storage)
    token = await web.create(7, "ana", KEY)

    credentials = await web.resolve(token)
    assert (credentials.login, credentials.uid, credentials.api_key) == ("ana", 7, KEY)
    assert KEY not in repr(credentials)
    (row,) = storage.rows.values()
    assert row.id_hash == hash_id(token) and token.encode() not in row.id_hash
    assert KEY.encode() not in row.key_encrypted


@pytest.mark.anyio
async def test_unknown_or_overlong_tokens_resolve_to_nobody():
    web = sessions()
    await web.create(7, "ana", KEY)
    assert await web.resolve("not-a-session") is None
    assert await web.resolve("") is None
    assert await web.resolve("x" * 500) is None


@pytest.mark.anyio
async def test_idle_sessions_end_and_activity_keeps_them_alive():
    clock = Clock()
    web = sessions(clock)
    token = await web.create(7, "ana", KEY)

    clock.now += timedelta(minutes=110)
    assert await web.resolve(token) is not None  # used: idle time starts again
    clock.now += timedelta(minutes=110)
    assert await web.resolve(token) is not None
    clock.now += timedelta(hours=2)
    assert await web.resolve(token) is None


@pytest.mark.anyio
async def test_sessions_end_after_their_lifetime_even_when_used():
    clock = Clock()
    web = sessions(clock)
    token = await web.create(7, "ana", KEY)
    for _ in range(13):
        clock.now += timedelta(minutes=59)
        result = await web.resolve(token)
    assert result is None  # 12 h 47 min after sign-in


@pytest.mark.anyio
async def test_a_stored_key_does_not_decrypt_under_another_session_id():
    storage = MemoryStorage()
    web = sessions(storage=storage)
    ana = await web.create(7, "ana", KEY)
    luis = await web.create(9, "luis", "fixture-not-a-real-credential-luis")
    # Someone with write access copies Ana's encrypted key into Luis's row.
    storage.rows[hash_id(luis)] = replace(
        storage.rows[hash_id(luis)], key_encrypted=storage.rows[hash_id(ana)].key_encrypted
    )
    assert await web.resolve(luis) is None


@pytest.mark.anyio
async def test_deleting_a_session_ends_it():
    web = sessions()
    token = await web.create(7, "ana", KEY)
    await web.delete(token)
    assert await web.resolve(token) is None


def test_cookie_parsing_and_origin_rules():
    headers = [(b"cookie", b"theme=dark; oag_session=abc123; other=1")]
    assert cookie_value(headers) == "abc123"
    assert cookie_value([(b"cookie", b"oag_session=")]) is None
    assert origin_allowed("http://127.0.0.1:8000", ORIGINS)
    assert origin_allowed("https://gw.example.com", (), own_origin="https://gw.example.com")
    assert not origin_allowed("https://evil.example", ORIGINS, "http://127.0.0.1:8000")
    assert not origin_allowed("http://127.0.0.1.evil.example", ORIGINS)
    assert not origin_allowed("null", ORIGINS)
    assert not origin_allowed("", ORIGINS)


# -- the middleware ----------------------------------------------------------------------------


def echo_app(scope, receive, send):
    async def run():
        headers = {k.decode(): v.decode() for k, v in scope["headers"]}
        body = json.dumps(
            {
                "login": headers.get("x-odoo-login"),
                "authorization": headers.get("authorization"),
            }
        ).encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    return run()


@pytest.fixture
def signed_in():
    web = sessions()
    token = anyio.run(web.create, 7, "ana", KEY)
    client = TestClient(
        WebSessionMiddleware(echo_app, web, ORIGINS), base_url="http://127.0.0.1:8000"
    )
    client.cookies.set(COOKIE_NAME, token)
    return client


def test_the_cookie_becomes_the_persons_headers_on_the_web_apis(signed_in):
    for path in ("/agent/models", "/approvals/pending", "/admin/providers", "/session"):
        assert signed_in.get(path).json() == {"login": "ana", "authorization": f"Bearer {KEY}"}


def test_the_cookie_never_reaches_mcp_or_other_paths(signed_in):
    for path in ("/mcp", "/health", "/app/", "/agentx"):
        assert signed_in.get(path).json() == {"login": None, "authorization": None}


def test_requests_with_their_own_credentials_are_left_alone(signed_in):
    response = signed_in.get(
        "/agent/models", headers={"x-odoo-login": "luis", "authorization": "Bearer other"}
    )
    assert response.json() == {"login": "luis", "authorization": "Bearer other"}


def test_changes_from_another_site_are_refused_before_anything_runs(signed_in):
    for origin in ("https://evil.example", None):
        headers = {"origin": origin} if origin else {}
        response = signed_in.post("/agent/conversations", json={}, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"] == "forbidden"
    ok = signed_in.post(
        "/agent/conversations", json={}, headers={"origin": "http://127.0.0.1:8000"}
    )
    assert ok.json()["login"] == "ana"


def test_an_unknown_cookie_adds_nothing(signed_in):
    signed_in.cookies.set(COOKIE_NAME, "forged")
    assert signed_in.get("/agent/models").json() == {"login": None, "authorization": None}


# -- sign in and out ---------------------------------------------------------------------------


def fake_odoo() -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        params = json.loads(request.content)["params"]
        if params["method"] == "authenticate":
            _, login, key, _ = params["args"]
            result = 7 if (login, key) == ("ana", KEY) else False
        else:
            model, method = params["args"][3], params["args"][4]
            result = {
                ("res.users", "read"): [{"id": 7, "name": "Ana García"}],
                ("res.users", "has_group"): False,
            }[(model, method)]
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": None, "result": result})

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def session_api(audit):
    settings = Settings(odoo_url="http://odoo.test", odoo_db="demo")
    gateway = Gateway(OdooProvider(settings, fake_odoo), audit, RateLimiter(100))
    web = sessions()
    app = FastAPI()
    app.include_router(
        build_session_router(gateway, web, "base.group_system", HOSTS, ORIGINS, None)
    )
    app.add_middleware(WebSessionMiddleware, sessions=web, allowed_origins=ORIGINS)
    return TestClient(app, base_url="http://127.0.0.1:8000"), web


def test_signing_in_sets_a_strict_cookie_and_never_returns_the_key():
    audit = MemoryAuditSink()
    client, web = session_api(audit)
    response = client.post(
        "/session",
        json={"login": "ana", "api_key": KEY},
        headers={"origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 200
    assert response.json() == {"login": "ana", "uid": 7, "name": "Ana García", "is_admin": False}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    for flag in ("HttpOnly", "SameSite=strict", "Path=/", "Max-Age=43200"):
        assert flag.lower() in cookie.lower()
    assert "secure" not in cookie.lower()  # plain http on localhost
    assert KEY not in response.text
    (event,) = audit.events
    assert (event.tool, event.login, event.outcome, event.arguments) == (
        "session.create",
        "ana",
        "ok",
        {},
    )

    me = client.get("/session")
    assert me.json()["name"] == "Ana García"
    assert KEY not in me.text

    out = client.delete("/session", headers={"origin": "http://127.0.0.1:8000"})
    assert out.json() == {"signed_out": True}
    assert client.get("/session").status_code == 401


def test_a_wrong_key_creates_no_session():
    client, web = session_api(MemoryAuditSink())
    response = client.post("/session", json={"login": "ana", "api_key": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthenticated"
    assert "set-cookie" not in response.headers
    assert web.storage.rows == {}


def test_sign_in_from_another_site_is_refused():
    client, web = session_api(MemoryAuditSink())
    response = client.post(
        "/session",
        json={"login": "ana", "api_key": KEY},
        headers={"origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert web.storage.rows == {}
