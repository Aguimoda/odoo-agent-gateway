"""Serving the web app (ADR 0019): headers, caching, client routes and path safety."""

from fastapi import FastAPI
from starlette.testclient import TestClient

from odoo_agent_gateway.web_app import CONTENT_SECURITY_POLICY, build_web_router


def client(dist) -> TestClient:
    app = FastAPI()
    app.include_router(build_web_router(dist))
    return TestClient(app, base_url="http://127.0.0.1:8000")


def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("outside", encoding="utf-8")
    return tmp_path


def test_without_a_build_the_app_explains_how_to_make_one(tmp_path):
    response = client(tmp_path / "missing").get("/app/")
    assert response.status_code == 503
    assert "npm --prefix web run build" in response.text


def test_root_redirects_to_the_app(tmp_path):
    response = client(built(tmp_path)).get("/", follow_redirects=False)
    assert response.status_code == 307 and response.headers["location"] == "/app/"


def test_index_is_never_cached_and_carries_the_security_headers(tmp_path):
    response = client(built(tmp_path)).get("/app/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    csp = response.headers["content-security-policy"]
    assert csp == CONTENT_SECURITY_POLICY
    for rule in ("script-src 'self'", "frame-ancestors 'none'", "connect-src 'self'"):
        assert rule in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_client_routes_get_the_index_and_hashed_assets_are_immutable(tmp_path):
    api = client(built(tmp_path))
    for path in ("/app/chat", "/app/chat/3f1c", "/app/admin/providers"):
        response = api.get(path)
        assert response.status_code == 200 and "id=root" in response.text
    asset = api.get("/app/assets/index-abc123.js")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert api.get("/app/favicon.svg").headers["cache-control"] == "no-cache"
    assert api.get("/app/assets/missing.js").status_code == 404


def test_paths_outside_the_build_are_not_served(tmp_path):
    api = client(built(tmp_path))
    for path in ("/app/../secret.txt", "/app/%2e%2e/secret.txt", "/app/..%2fsecret.txt"):
        assert "outside" not in api.get(path).text


def test_only_the_configured_odoo_may_show_the_app_in_a_panel(tmp_path):
    """ADR 0021: frame-ancestors lists Odoo; without it, no framing at all."""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    app = FastAPI()
    app.include_router(build_web_router(tmp_path, embed_origins=("http://127.0.0.1:8069",)))
    response = TestClient(app).get("/app/embed/chat")
    csp = response.headers["content-security-policy"]
    assert "frame-ancestors 'self' http://127.0.0.1:8069" in csp
    assert "x-frame-options" not in response.headers

    plain = FastAPI()
    plain.include_router(build_web_router(tmp_path))
    headers = TestClient(plain).get("/app/").headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-frame-options"] == "DENY"
