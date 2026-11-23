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
        # Odoo (M8) frames the app and, from its container, hands keys over.
        allowed_hosts=("127.0.0.1:*", "localhost:*", "host.docker.internal:*"),
        embed_origins=(demo["ODOO_URL"].rstrip("/"),),
    )
    port = free_port()
    # On Linux, Odoo's container reaches the host's bridge address, not its loopback.
    bind = os.environ.get("E2E_GATEWAY_BIND", "127.0.0.1")
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host=bind, port=port, log_level="warning")
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


def test_the_next_person_starts_on_a_new_conversation(page, demo, models):
    """Scenario: entrar como otra persona (M7.1)."""
    from playwright.sync_api import expect

    sign_in(page, demo, "ana")
    page.get_by_label("Modelo").select_option(
        label=f"{models['good']} · e2e-good-{models['good'][-6:]}"
    )
    ask(page, "¿Cuál es el plazo de envío?")
    expect(page.get_by_role("button", name="Copiar respuesta")).to_have_count(1, timeout=30_000)
    assert "/app/chat/" in page.url  # Ana is on her conversation
    page.get_by_role("button", name="Cuenta y preferencias").click()
    page.get_by_role("menuitem", name="Salir").click()

    # Luis signs in on the same page, without reloading it.
    page.get_by_label("Usuario de Odoo").fill(demo["DEMO_LUIS_LOGIN"])
    page.get_by_label("Clave API de Odoo").fill(demo["DEMO_LUIS_API_KEY"])
    page.get_by_role("button", name="Entrar").click()
    expect(page.get_by_role("heading", name="¿En qué te ayudo, Luis")).to_be_visible()
    assert page.url.rstrip("/").endswith("/app/chat")
    expect(page.get_by_label("Escribe un mensaje…")).to_be_enabled()


def test_carmen_browses_a_providers_models_and_adds_one(page, demo, models):
    """Scenarios: ver los modelos disponibles; añadir un modelo desde la lista (M7.1)."""
    from playwright.sync_api import expect

    sign_in(page, demo, "carmen")
    page.get_by_role("link", name="Administración").click()
    panel = page.get_by_role("article").filter(
        has=page.get_by_role("heading", name=f"e2e-good-{models['good'][-6:]}")
    )
    panel.get_by_role("button", name="Ver modelos disponibles").click()
    catalog = panel.get_by_role("region", name="Modelos disponibles")
    added = catalog.get_by_role("row").filter(has_text="scripted-mini")
    expect(added).to_contain_text("Añadido")
    other = catalog.get_by_role("row").filter(has_text="scripted-large")
    other.get_by_role("button", name="Añadir: scripted-large").click()
    expect(other).to_contain_text("Añadido")
    assert page.csp_errors == []


# -- M8: the assistant inside Odoo (ADR 0021) -------------------------------------------------

KEY_NAME = "Odoo Agent Gateway (assistant)"


def odoo_rpc(demo, login: str, secret: str, model: str, method: str, args, kwargs=None):
    """JSON-RPC to the demo Odoo as someone (password or API key)."""
    import urllib.request

    def call(service, rpc_method, *rpc_args):
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
        answer = json.load(urllib.request.urlopen(request))
        if "error" in answer:
            raise AssertionError(answer["error"]["data"]["message"])
        return answer["result"]

    uid = call("common", "authenticate", demo["ODOO_DB"], login, secret, {})
    return uid, call(
        "object", "execute_kw", demo["ODOO_DB"], uid, secret, model, method, args, kwargs or {}
    )


def as_admin(demo, model, method, args, kwargs=None):
    return odoo_rpc(demo, "admin", demo["DEMO_ADMIN_PASSWORD"], model, method, args, kwargs)[1]


def as_person(demo, who, model, method, args, kwargs=None):
    login, key = demo[f"DEMO_{who.upper()}_LOGIN"], demo[f"DEMO_{who.upper()}_API_KEY"]
    return odoo_rpc(demo, login, key, model, method, args, kwargs)


@pytest.fixture(scope="module")
def odoo_assistant(demo, gateway):
    """Point the demo Odoo's module at this test gateway; put its settings back afterwards."""
    if "DEMO_ANA_PASSWORD" not in demo:
        missing("Demo data predates M8: run scripts/demo/setup_demo.py again.")
    keys = ("public_url", "server_url")
    before = {
        k: as_admin(demo, "ir.config_parameter", "get_param", [f"agent_gateway_connector.{k}"])
        for k in keys
    }
    port = gateway.rsplit(":", 1)[1]
    as_admin(
        demo, "ir.config_parameter", "set_param", ["agent_gateway_connector.public_url", gateway]
    )
    as_admin(
        demo,
        "ir.config_parameter",
        "set_param",
        ["agent_gateway_connector.server_url", f"http://host.docker.internal:{port}"],
    )
    for who in ("ana", "luis"):  # start from "never used the assistant"
        uid, _ = as_person(demo, who, "res.users", "agent_gateway_status", [])
        as_person(demo, who, "res.users", "agent_gateway_revoke", [[uid]])
    yield
    for who in ("ana", "luis"):
        uid, _ = as_person(demo, who, "res.users", "agent_gateway_status", [])
        as_person(demo, who, "res.users", "agent_gateway_revoke", [[uid]])
    for key, value in before.items():
        as_admin(
            demo,
            "ir.config_parameter",
            "set_param",
            [f"agent_gateway_connector.{key}", value or ""],
        )


def odoo_sign_in(page, demo, who: str) -> None:
    page.goto(demo["ODOO_URL"] + "/web/login?db=" + demo["ODOO_DB"])
    page.get_by_label("Email").fill(demo[f"DEMO_{who.upper()}_LOGIN"])
    page.get_by_label("Password").fill(demo[f"DEMO_{who.upper()}_PASSWORD"])
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("button", name="AI assistant").wait_for(timeout=30_000)


def assistant_keys(demo, who: str) -> list[dict]:
    uid, _ = as_person(demo, who, "res.users", "agent_gateway_status", [])
    return as_admin(
        demo,
        "res.users.apikeys",
        "search_read",
        [[["user_id", "=", uid], ["name", "=", KEY_NAME]]],
        {"fields": ["scope", "expiration_date"]},
    )


def test_ana_uses_the_assistant_inside_odoo_and_revokes_it(page, demo, models, odoo_assistant):
    """Scenarios: primer uso con consentimiento; chat dentro de Odoo; retirar el acceso."""
    from playwright.sync_api import expect

    odoo_sign_in(page, demo, "ana")
    page.get_by_role("button", name="AI assistant").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Allow the assistant to act on your behalf?")
    assert assistant_keys(demo, "ana") == []  # nothing before consent
    dialog.get_by_role("button", name="Allow").click()

    panel = page.frame_locator(".o_agent_gateway_panel iframe")
    expect(panel.get_by_role("heading", name="¿En qué te ayudo, Ana")).to_be_visible(timeout=30_000)
    (key,) = assistant_keys(demo, "ana")
    assert key["scope"] == "rpc"
    frame = next(f for f in page.frames if "/app/embed/" in f.url)
    assert "ticket=" not in frame.url  # the ticket left the address at once

    panel.get_by_label("Modelo").select_option(
        label=f"{models['good']} · e2e-good-{models['good'][-6:]}"
    )
    box = panel.get_by_label("Escribe un mensaje…")
    box.fill("¿Cuál es el plazo de envío?")
    box.press("Enter")
    expect(panel.get_by_role("button", name="Usó 1 herramienta como ana")).to_be_visible(
        timeout=30_000
    )

    uid, _ = as_person(demo, "ana", "res.users", "agent_gateway_status", [])
    as_person(demo, "ana", "res.users", "agent_gateway_revoke", [[uid]])
    assert assistant_keys(demo, "ana") == []
    # The panel's gateway session died with the key, at once.
    assert page.request.get(gateway_url(page) + "/session").status == 401
    # Opening the panel again asks for consent again; nothing opens without it.
    page.get_by_role("button", name="AI assistant").click()  # closes the panel
    page.get_by_role("button", name="AI assistant").click()
    expect(page.get_by_role("dialog")).to_contain_text("Allow the assistant to act on your behalf?")
    page.get_by_role("dialog").get_by_role("button", name="Not now").click()
    expect(page.locator(".o_agent_gateway_panel")).to_have_count(0)
    assert assistant_keys(demo, "ana") == []


def gateway_url(page) -> str:
    frame = next(f for f in page.frames if "/app/embed/" in f.url)
    return frame.url.split("/app/", 1)[0]


def test_luis_opens_the_inbox_from_odoos_menu_and_ana_has_no_administration(
    page, demo, models, odoo_assistant
):
    """Scenario: bandeja y administración desde los menús de Odoo."""
    from playwright.sync_api import expect

    odoo_sign_in(page, demo, "luis")
    page.goto(demo["ODOO_URL"] + "/odoo/action-agent_gateway_connector.action_assistant_approvals")
    page.get_by_role("dialog").get_by_role("button", name="Allow").click()
    inbox = page.frame_locator(".o_agent_gateway_action iframe")
    expect(inbox.get_by_text("Aprobaciones").first).to_be_visible(timeout=30_000)

    menus = as_person(demo, "ana", "ir.ui.menu", "load_menus", [False])[1]
    names = {menu["name"] for menu in menus.values() if isinstance(menu, dict) and "name" in menu}
    assert "Approvals" in names and "Administration" not in names
