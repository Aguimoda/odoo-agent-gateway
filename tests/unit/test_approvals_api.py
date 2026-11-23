"""The /approvals HTTP API: authentication, audit, error codes and host checks.

The approval rules themselves are covered in test_proposals.py; here a stub service records
which session reached it and can raise the gateway's errors.
"""

import json

import httpx2
import pytest
from starlette.testclient import TestClient

from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.approvals import host_allowed
from odoo_agent_gateway.audit import MemoryAuditSink
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.odoo import AccessDenied, InvalidRequest
from odoo_agent_gateway.proposals import Conflict, FourEyes

KEY = "luis-real-key-0123456789"
SETTINGS = Settings(odoo_url="http://odoo.test", odoo_db="demo")
LOCAL = "http://127.0.0.1:8000"


def fake_odoo() -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        params = json.loads(request.content)["params"]
        _, login, key, _ = params["args"]
        uid = 9 if (login, key) == ("luis", KEY) else False
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": None, "result": uid})

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


class StubProposals:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple] = []

    async def _answer(self, *call):
        self.calls.append(call)
        if self.error:
            raise self.error
        return {"proposal_id": 1, "status": "applied"}

    async def pending_for(self, session, limit=None):
        self.calls.append(("pending", session.uid, limit))
        return {"proposals": [{"proposal_id": 1}]}

    async def list_mine(self, session, status=None, limit=None):
        self.calls.append(("mine", session.uid, status, limit))
        return {"proposals": [{"proposal_id": 2, "status": "pending"}]}

    async def approve(self, session, proposal_id, note):
        return await self._answer("approve", session.uid, proposal_id, note)

    async def reject(self, session, proposal_id, note):
        return await self._answer("reject", session.uid, proposal_id, note)


def client(proposals=None, audit=None, base_url=LOCAL):
    app = create_app(
        SETTINGS,
        http_client_factory=fake_odoo,
        audit_sink=audit or MemoryAuditSink(),
        proposals=proposals or StubProposals(),
    )
    return TestClient(app, base_url=base_url)


LUIS = {"x-odoo-login": "luis", "authorization": f"Bearer {KEY}"}


def test_approving_reaches_the_service_as_the_authenticated_approver():
    proposals, audit = StubProposals(), MemoryAuditSink()

    with client(proposals, audit) as api:
        response = api.post("/approvals/1/approve", json={"note": "Checked."}, headers=LUIS)

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    assert proposals.calls == [("approve", 9, 1, "Checked.")]
    (event,) = audit.events
    assert (event.tool, event.login, event.odoo_uid, event.outcome) == (
        "approvals.approve",
        "luis",
        9,
        "ok",
    )
    assert event.arguments == {"proposal_id": 1, "note": "Checked."}


def test_pending_and_reject_work_too():
    proposals = StubProposals()

    with client(proposals) as api:
        pending = api.get("/approvals/pending", headers=LUIS)
        rejected = api.post("/approvals/1/reject", json={"note": "No."}, headers=LUIS)

    assert pending.json() == {"proposals": [{"proposal_id": 1}]}
    assert proposals.calls[0] == ("pending", 9, None)
    assert rejected.status_code == 200
    assert proposals.calls[-1] == ("reject", 9, 1, "No.")


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (FourEyes("own proposal"), 403, "four_eyes"),
        (AccessDenied("cannot see"), 403, "forbidden"),
        (Conflict("already applied"), 409, "conflict"),
        (InvalidRequest("bad"), 422, "invalid_request"),
    ],
)
def test_gateway_errors_become_http_status_codes(error, status, code):
    with client(StubProposals(error)) as api:
        response = api.post("/approvals/1/approve", json={}, headers=LUIS)

    assert response.status_code == status
    assert response.json()["error"] == code


@pytest.mark.parametrize(
    "headers",
    [{}, {"x-odoo-login": "luis", "authorization": "Bearer made-up-key"}],
)
def test_approvals_need_valid_credentials_which_are_never_echoed(headers):
    proposals, audit = StubProposals(), MemoryAuditSink()

    with client(proposals, audit) as api:
        response = api.post("/approvals/1/approve", json={}, headers=headers)

    assert response.status_code == 401
    assert "made-up-key" not in response.text
    assert proposals.calls == []
    assert audit.events[0].outcome == "unauthenticated"


def test_no_audit_means_no_decision():
    proposals = StubProposals()

    with client(proposals, MemoryAuditSink(available=False)) as api:
        response = api.post("/approvals/1/approve", json={}, headers=LUIS)

    assert response.status_code == 503
    assert response.json()["error"] == "audit_unavailable"


def test_requests_with_an_unexpected_host_are_refused():
    proposals = StubProposals()

    with client(proposals, base_url="http://evil.example") as api:
        response = api.post("/approvals/1/approve", json={}, headers=LUIS)

    assert response.status_code == 421
    assert proposals.calls == []


def test_without_a_proposals_store_the_api_says_so():
    app = create_app(SETTINGS, http_client_factory=fake_odoo, audit_sink=MemoryAuditSink())

    with TestClient(app, base_url=LOCAL) as api:
        response = api.get("/approvals/pending", headers=LUIS)

    assert response.status_code == 503
    assert response.json()["error"] == "proposals_unavailable"


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("127.0.0.1:8000", True),
        ("localhost:9", True),
        ("127.0.0.1", True),
        ("gateway.example.com", True),
        ("evil.example", False),
        ("127.0.0.1.evil.example:80", False),
        ("", False),
    ],
)
def test_host_patterns(host, allowed):
    patterns = ("127.0.0.1:*", "localhost:*", "gateway.example.com")

    assert host_allowed(host, patterns) is allowed


def test_mine_lists_the_callers_own_proposals():
    proposals, audit = StubProposals(), MemoryAuditSink()

    with client(proposals, audit) as api:
        response = api.get("/approvals/mine?status=pending&limit=5", headers=LUIS)

    assert response.json()["proposals"][0]["proposal_id"] == 2
    assert proposals.calls == [("mine", 9, "pending", 5)]
    assert audit.events[0].tool == "approvals.mine"
