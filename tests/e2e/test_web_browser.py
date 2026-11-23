"""M7 acceptance in a real browser: the built web app against real Odoo (ADR 0018, 0019).

Needs the Docker stack, the demo data, the built app (`npm --prefix web run build`) and
Chromium for Playwright (`python -m playwright install chromium`). The language model is
the scripted one from scripts/demo/fake_llm.py, served on a free local port.
"""

import importlib.util
import json
import os
import socket
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx2
import pytest

from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.secretbox import new_master_key
from odoo_agent_gateway.web_app import DEFAULT_WEB_DIR

pytestmark = [pytest.mark.integration, pytest.mark.e2e]

ROOT = Path(__file__).resolve().parents[2]
KEYS_FILE = ROOT / ".env.demo-keys"


def missing(reason: str):
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def demo() -> dict[str, str]:
    if not KEYS_FILE.exists():
        missing("Demo data missing: run scripts/demo/setup_demo.py first.")
    if not (DEFAULT_WEB_DIR / "index.html").exists():
        missing("Web app not built: run npm --prefix web ci && npm --prefix web run build.")
    lines = KEYS_FILE.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


@pytest.fixture(scope="module")
def fake_llm() -> str:
    spec = importlib.util.spec_from_file_location("fake_llm", ROOT / "scripts/demo/fake_llm.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = ThreadingHTTPServer(("127.0.0.1", free_port()), module.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def gateway(demo) -> str:
    import uvicorn

    settings = Settings(
        odoo_url=demo["ODOO_URL"],
        odoo_db=demo["ODOO_DB"],
        database_url=demo["GATEWAY_DATABASE_URL"],
        rate_limit_per_minute=1000,
        model_cache=os.environ.get("GATEWAY_MODEL_CACHE", ".cache/models"),
        secret_keys=new_master_key(),
        agent_messages_per_minute=1000,
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 120
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            pytest.fail("The gateway did not start.")
        time.sleep(0.2)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def headers(demo, who: str) -> dict[str, str]:
    return {
        "x-odoo-login": demo[f"DEMO_{who.upper()}_LOGIN"],
        "authorization": f"Bearer {demo[f'DEMO_{who.upper()}_API_KEY']}",
    }


@pytest.fixture(scope="module")
def models(gateway, fake_llm, demo) -> dict[str, str]:
    """Two scripted providers, registered through the admin API; removed afterwards."""
    suffix = uuid.uuid4().hex[:6]
    carmen = headers(demo, "carmen")
    labels, created = {}, []
    with httpx2.Client(base_url=gateway, timeout=30) as http:
        for kind in ("good", "limited"):
            provider = http.post(
                "/admin/providers",
                json={
                    "name": f"e2e-{kind}-{suffix}",
                    "base_url": f"{fake_llm}/{kind}/v1",
                    "api_key": "scripted-model-needs-no-real-key",
                },
                headers=carmen,
            ).json()
            created.append(provider["id"])
            label = f"E2E {kind} {suffix}"
            http.post(
                f"/admin/providers/{provider['id']}/models",
                json={"name": "scripted-mini", "label": label},
                headers=carmen,
            ).raise_for_status()
            labels[kind] = label
        before = {
            who: {
                c["id"]
                for c in http.get("/agent/conversations", headers=headers(demo, who)).json()[
                    "conversations"
                ]
            }
            for who in ("ana", "luis", "carmen")
        }
        yield labels
        for provider_id in created:
            http.delete(f"/admin/providers/{provider_id}", headers=carmen)
        for who, known in before.items():  # the conversations the browser tests started
            listed = http.get("/agent/conversations", headers=headers(demo, who)).json()[
                "conversations"
            ]
            for conversation in listed:
                if conversation["id"] not in known:
                    http.delete(
                        f"/agent/conversations/{conversation['id']}", headers=headers(demo, who)
                    )


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except Exception as error:  # browser not installed
            missing(f"Chromium for Playwright is missing: {error}")
        yield instance
        instance.close()


@pytest.fixture
def page(browser, gateway):
    context = browser.new_context(
        base_url=gateway, locale="es-ES", viewport={"width": 1280, "height": 860}
    )
    page = context.new_page()
    page.csp_errors = []
    page.on(
        "console",
        lambda message: (
            "Content Security Policy" in message.text and page.csp_errors.append(message.text)
        ),
    )
    yield page
    context.close()


def sign_in(page, demo, who: str) -> None:
    page.goto("/app/")
    page.get_by_label("Usuario de Odoo").fill(demo[f"DEMO_{who.upper()}_LOGIN"])
    page.get_by_label("Clave API de Odoo").fill(demo[f"DEMO_{who.upper()}_API_KEY"])
    page.get_by_role("button", name="Entrar").click()
    page.get_by_role("button", name="Cuenta y preferencias").wait_for()


def ask(page, text: str) -> None:
    box = page.get_by_label("Escribe un mensaje…")
    box.fill(text)
    box.press("Enter")


def test_ana_chats_sees_what_was_used_and_picks_another_model_on_a_limit(page, demo, models):
    """Scenarios: el chat usa la sesión; error del proveedor con elección."""
    sign_in(page, demo, "ana")
    from playwright.sync_api import expect

    expect(page.get_by_role("heading", name="¿En qué te ayudo, Ana")).to_be_visible()
    # The key is not reachable from the page: not in storage, and the cookie is HttpOnly.
    key = demo["DEMO_ANA_API_KEY"]
    storage = page.evaluate(
        "() => JSON.stringify({...localStorage, ...sessionStorage}) + document.cookie"
    )
    assert key not in storage and "oag_session" not in storage

    page.get_by_label("Modelo").select_option(
        label=f"{models['good']} · e2e-good-{models['good'][-6:]}"
    )
    ask(page, "¿Cuál es el plazo de envío?")
    expect(page.get_by_text("resultado(s) con tus permisos")).to_be_visible(timeout=30_000)
    expect(page.get_by_role("button", name="Usó 1 herramienta como ana")).to_be_visible()
    expect(page.get_by_role("button", name="Copiar respuesta")).to_have_count(1)  # finished

    page.get_by_label("Modelo").select_option(
        label=f"{models['limited']} · e2e-limited-{models['limited'][-6:]}"
    )
    ask(page, "¿Y para Canarias?")
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("ha llegado a su límite por minuto", timeout=30_000)
    expect(alert).to_contain_text("Puedes reintentar en")
    alert.get_by_role("button", name=models["good"]).click()
    expect(page.get_by_text("resultado(s) con tus permisos")).to_have_count(2, timeout=30_000)
    assert page.csp_errors == []


def test_luis_approves_from_the_inbox_and_odoo_changes(page, gateway, demo):
    """Scenario: aprobar desde la bandeja."""
    import urllib.request

    from playwright.sync_api import expect

    def odoo(who, model, method, args):
        login, key = demo[f"DEMO_{who.upper()}_LOGIN"], demo[f"DEMO_{who.upper()}_API_KEY"]

        def rpc(service, rpc_method, *rpc_args):
            body = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"service": service, "method": rpc_method, "args": list(rpc_args)},
            }
            request = urllib.request.Request(
                demo["ODOO_URL"] + "/jsonrpc",
                json.dumps(body).encode(),
                {"Content-Type": "application/json"},
            )
            return json.load(urllib.request.urlopen(request))["result"]

        uid = rpc("common", "authenticate", demo["ODOO_DB"], login, key, {})
        return rpc("object", "execute_kw", demo["ODOO_DB"], uid, key, model, method, args, {})

    (acme,) = odoo("luis", "res.partner", "search", [[["name", "=", "Acme Demo SL"]]])
    (original,) = odoo("luis", "res.partner", "read", [[acme], ["phone"]])
    phone = f"+34 611 {uuid.uuid4().int % 1_000_000:06d}"
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "propose_change",
            "arguments": {
                "model": "res.partner",
                "record_id": acme,
                "values": {"phone": phone},
                "reason": "Browser test: new phone from a call.",
            },
        },
    }
    mcp = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        **headers(demo, "ana"),
    }
    result = httpx2.post(f"{gateway}/mcp", json=call, headers=mcp, timeout=30).json()["result"]
    assert not result["isError"], result
    try:
        sign_in(page, demo, "luis")
        page.get_by_role("link", name="Aprobaciones").click()
        card = page.get_by_role("article").filter(has_text=phone)
        expect(card).to_contain_text("ana propone cambiar res.partner")
        card.get_by_label("Nota (opcional)").fill("Confirmado por teléfono.")
        card.get_by_role("button", name="Aprobar y aplicar").click()
        expect(card).to_contain_text("Aplicada", timeout=30_000)
        (row,) = odoo("luis", "res.partner", "read", [[acme], ["phone"]])
        assert row["phone"] == phone
        assert page.csp_errors == []
    finally:
        odoo("luis", "res.partner", "write", [[acme], {"phone": original["phone"]}])


def test_only_administrators_see_the_panel(page, demo, models):
    """Scenario: el panel solo para administradores."""
    from playwright.sync_api import expect

    sign_in(page, demo, "ana")
    expect(page.get_by_role("link", name="Administración")).to_have_count(0)
    page.goto("/app/admin/providers")
    expect(page.get_by_text("Esta sección es solo para administradores")).to_be_visible()
    page.get_by_role("button", name="Cuenta y preferencias").click()
    page.get_by_role("menuitem", name="Salir").click()

    sign_in(page, demo, "carmen")
    page.get_by_role("link", name="Administración").click()
    expect(page.get_by_role("heading", name=f"e2e-good-{models['good'][-6:]}")).to_be_visible()
    assert page.csp_errors == []
