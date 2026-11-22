"""M4 acceptance scenarios: proposals and four-eyes approval against the real Odoo.

Run with:  pytest -m integration
Proposals are never deleted (by design), so each test uses unique values and restores Odoo.
"""

import json
import os
import urllib.request
import uuid
from pathlib import Path

import anyio
import asyncpg
import pytest
from starlette.testclient import TestClient

from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.config import Settings

pytestmark = pytest.mark.integration

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"
REASON = "The customer called to give us a new phone number."


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


@pytest.fixture(scope="module")
def gateway(demo):
    settings = Settings(
        odoo_url=demo["ODOO_URL"],
        odoo_db=demo["ODOO_DB"],
        database_url=demo["GATEWAY_DATABASE_URL"],
        rate_limit_per_minute=1000,
        model_cache=os.environ.get("GATEWAY_MODEL_CACHE", ".cache/models"),
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
        yield client


def headers(demo, who: str) -> dict[str, str]:
    return {
        "x-odoo-login": demo[f"DEMO_{who.upper()}_LOGIN"],
        "authorization": f"Bearer {demo[f'DEMO_{who.upper()}_API_KEY']}",
    }


def tool(gateway, demo, who: str, name: str, arguments: dict):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    mcp_headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        **headers(demo, who),
    }
    result = gateway.post("/mcp", json=body, headers=mcp_headers).json()["result"]
    text = result["content"][0]["text"]
    return (True, text) if result["isError"] else (False, json.loads(text))


def decide(gateway, demo, who: str, proposal_id: int, action: str, note: str | None = None):
    return gateway.post(
        f"/approvals/{proposal_id}/{action}", json={"note": note}, headers=headers(demo, who)
    )


def odoo(demo, who: str, model: str, method: str, args: list, kwargs: dict | None = None):
    """Talk to Odoo directly as a demo user, to check or set up state outside the gateway."""
    login, key = demo[f"DEMO_{who.upper()}_LOGIN"], demo[f"DEMO_{who.upper()}_API_KEY"]

    def rpc(service, rpc_method, *rpc_args):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": rpc_method, "args": list(rpc_args)},
        }
        request = urllib.request.Request(
            demo["ODOO_URL"] + "/jsonrpc",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json"},
        )
        return json.load(urllib.request.urlopen(request))["result"]

    uid = rpc("common", "authenticate", demo["ODOO_DB"], login, key, {})
    return rpc("object", "execute_kw", demo["ODOO_DB"], uid, key, model, method, args, kwargs or {})


@pytest.fixture(scope="module")
def acme(demo) -> int:
    (partner_id,) = odoo(demo, "luis", "res.partner", "search", [[["name", "=", "Acme Demo SL"]]])
    return partner_id


def phone_of(demo, partner_id: int):
    (row,) = odoo(demo, "luis", "res.partner", "read", [[partner_id], ["phone", "write_uid"]])
    return row


def unique_phone() -> str:
    return f"+34 600 {uuid.uuid4().int % 1_000_000:06d}"


@pytest.fixture
def restore_acme_phone(demo, acme):
    original = phone_of(demo, acme)["phone"]
    yield
    odoo(demo, "luis", "res.partner", "write", [[acme], {"phone": original}])


# --- the main flow -------------------------------------------------------------------------


def test_ana_proposes_luis_approves_and_the_write_runs_as_luis(
    gateway, demo, acme, restore_acme_phone
):
    new_phone = unique_phone()

    error, proposal = tool(
        gateway,
        demo,
        "ana",
        "propose_change",
        {
            "model": "res.partner",
            "record_id": acme,
            "values": {"phone": new_phone},
            "reason": REASON,
        },
    )
    assert not error and proposal["status"] == "pending"
    assert phone_of(demo, acme)["phone"] != new_phone  # nothing changed yet

    response = decide(
        gateway, demo, "luis", proposal["proposal_id"], "approve", "Confirmed by phone."
    )

    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["decided_by"]) == ("applied", "luis")
    after = phone_of(demo, acme)
    assert after["phone"] == new_phone
    assert after["write_uid"][1] == "Luis (Management)"  # Odoo recorded Luis as the writer

    _, mine = tool(gateway, demo, "ana", "list_my_proposals", {"status": "applied"})
    assert proposal["proposal_id"] in [p["proposal_id"] for p in mine["proposals"]]
    rows = anyio.run(audit_rows, demo, proposal["proposal_id"])
    assert ("approvals.approve", "luis", "ok") in rows


async def audit_rows(demo, proposal_id: int):
    connection = await asyncpg.connect(demo["GATEWAY_DATABASE_URL"])
    try:
        rows = await connection.fetch(
            "select tool, login, outcome from audit_log where arguments->>'proposal_id' = $1",
            str(proposal_id),
        )
    finally:
        await connection.close()
    return [(row["tool"], row["login"], row["outcome"]) for row in rows]


def test_nobody_approves_their_own_proposal(gateway, demo):
    ana_order = int(demo["DEMO_ANA_ORDER_IDS"].split(",")[0])
    _, proposal = tool(
        gateway,
        demo,
        "ana",
        "propose_change",
        {
            "model": "sale.order",
            "record_id": ana_order,
            "values": {"client_order_ref": f"REF-{uuid.uuid4().hex[:6]}"},
            "reason": "The customer sent a new purchase order reference.",
        },
    )

    response = decide(gateway, demo, "ana", proposal["proposal_id"], "approve")

    assert response.status_code == 403
    assert response.json()["error"] == "four_eyes"
    withdrawn = decide(
        gateway, demo, "ana", proposal["proposal_id"], "reject", "Withdrawn by test."
    )
    assert withdrawn.json()["status"] == "rejected"


def test_odoo_rechecks_the_approver_who_cannot_see_the_record(gateway, demo):
    luis_order = int(demo["DEMO_LUIS_ORDER_IDS"].split(",")[1])
    _, proposal = tool(
        gateway,
        demo,
        "luis",
        "propose_change",
        {
            "model": "sale.order",
            "record_id": luis_order,
            "values": {"client_order_ref": f"REF-{uuid.uuid4().hex[:6]}"},
            "reason": "Updating the customer reference for this order.",
        },
    )

    response = decide(gateway, demo, "ana", proposal["proposal_id"], "approve")

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    _, still = tool(gateway, demo, "luis", "list_my_proposals", {"status": "pending"})
    assert proposal["proposal_id"] in [p["proposal_id"] for p in still["proposals"]]
    decide(gateway, demo, "luis", proposal["proposal_id"], "reject", "Withdrawn by test.")


def test_a_record_changed_after_the_proposal_is_a_conflict(gateway, demo, acme, restore_acme_phone):
    _, proposal = tool(
        gateway,
        demo,
        "ana",
        "propose_change",
        {
            "model": "res.partner",
            "record_id": acme,
            "values": {"phone": unique_phone()},
            "reason": REASON,
        },
    )
    direct = unique_phone()
    odoo(
        demo, "luis", "res.partner", "write", [[acme], {"phone": direct}]
    )  # someone edits meanwhile

    response = decide(gateway, demo, "luis", proposal["proposal_id"], "approve")

    assert response.json()["status"] == "conflict"
    assert phone_of(demo, acme)["phone"] == direct  # the newer value was not overwritten


def test_a_decision_is_final(gateway, demo, acme, restore_acme_phone):
    _, proposal = tool(
        gateway,
        demo,
        "ana",
        "propose_change",
        {
            "model": "res.partner",
            "record_id": acme,
            "values": {"phone": unique_phone()},
            "reason": REASON,
        },
    )
    decide(gateway, demo, "luis", proposal["proposal_id"], "reject", "Wrong number.")

    again = decide(gateway, demo, "luis", proposal["proposal_id"], "approve")

    assert again.status_code == 409
    assert again.json()["error"] == "conflict"


# --- what cannot be proposed ---------------------------------------------------------------


@pytest.mark.parametrize(
    "values",
    [
        {"state": "cancel"},  # workflow state
        {"amount_total": 1},  # read-only
        {"order_line": [[5, 0, 0]]},  # line list
        {"colour": "blue"},  # unknown field
    ],
)
def test_forbidden_changes_are_refused(gateway, demo, values):
    ana_order = int(demo["DEMO_ANA_ORDER_IDS"].split(",")[0])

    error, text = tool(
        gateway,
        demo,
        "ana",
        "propose_change",
        {
            "model": "sale.order",
            "record_id": ana_order,
            "values": values,
            "reason": "Trying something that must be refused.",
        },
    )

    assert error and "invalid_request" in text


def test_nobody_proposes_changes_to_records_they_cannot_see(gateway, demo):
    luis_order = int(demo["DEMO_LUIS_ORDER_IDS"].split(",")[0])

    error, text = tool(
        gateway,
        demo,
        "ana",
        "propose_change",
        {
            "model": "sale.order",
            "record_id": luis_order,
            "values": {"client_order_ref": "X"},
            "reason": "Trying to touch an order of someone else.",
        },
    )

    assert error and "forbidden" in text


def test_pending_lists_follow_what_each_approver_can_see(gateway, demo, acme):
    _, by_ana = tool(
        gateway,
        demo,
        "ana",
        "propose_change",
        {
            "model": "res.partner",
            "record_id": acme,
            "values": {"phone": unique_phone()},
            "reason": REASON,
        },
    )
    luis_order = int(demo["DEMO_LUIS_ORDER_IDS"].split(",")[1])
    _, by_luis = tool(
        gateway,
        demo,
        "luis",
        "propose_change",
        {
            "model": "sale.order",
            "record_id": luis_order,
            "values": {"client_order_ref": f"REF-{uuid.uuid4().hex[:6]}"},
            "reason": "Updating the customer reference for this order.",
        },
    )
    try:
        for_luis = decide_list(gateway, demo, "luis")
        for_ana = decide_list(gateway, demo, "ana")

        assert by_ana["proposal_id"] in for_luis
        assert "current" in for_luis[by_ana["proposal_id"]]
        assert by_luis["proposal_id"] not in for_ana  # Ana cannot see Luis's order
        assert by_ana["proposal_id"] not in for_ana  # nor approve her own
    finally:
        decide(gateway, demo, "ana", by_ana["proposal_id"], "reject", "Withdrawn by test.")
        decide(gateway, demo, "luis", by_luis["proposal_id"], "reject", "Withdrawn by test.")


def decide_list(gateway, demo, who: str) -> dict[int, dict]:
    response = gateway.get("/approvals/pending?limit=50", headers=headers(demo, who))
    assert response.status_code == 200, response.text
    return {p["proposal_id"]: p for p in response.json()["proposals"]}
