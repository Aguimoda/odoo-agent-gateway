"""The approval API (ADR 0012): where a different person decides on proposals.

It is deliberately not an MCP tool. It uses the same Gateway path as the tools (rate limit,
credentials checked by Odoo, audit with fail-closed), and the approver's own credentials.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from odoo_agent_gateway.gateway import Gateway
from odoo_agent_gateway.odoo import OdooError, OdooSession
from odoo_agent_gateway.proposal_store import ProposalsUnavailable

HTTP_STATUS = {
    "unauthenticated": 401,
    "forbidden": 403,
    "four_eyes": 403,
    "not_found": 404,
    "conflict": 409,
    "invalid_request": 422,
    "rate_limited": 429,
    "internal_error": 500,
    "odoo_unavailable": 502,
    "audit_unavailable": 503,
    "proposals_unavailable": 503,
}


class DecisionBody(BaseModel):
    note: str | None = None


def host_allowed(host: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Same host rules as the MCP endpoint (ADR 0007): 'name' or 'name:*' for any port."""
    host = (host or "").strip().lower()
    if not host:
        return False
    for pattern in patterns:
        pattern = pattern.lower()
        if pattern.endswith(":*"):
            base = pattern[:-2]
            if host == base or host.startswith(base + ":"):
                return True
        elif host == pattern:
            return True
    return False


def build_approval_router(
    gateway: Gateway, proposals: Any, allowed_hosts: tuple[str, ...]
) -> APIRouter:
    router = APIRouter(prefix="/approvals", tags=["approvals"])

    async def respond(
        request: Request,
        tool: str,
        arguments: dict[str, Any],
        action: Callable[[OdooSession], Awaitable[Any]],
    ) -> Any:
        if not host_allowed(request.headers.get("host", ""), allowed_hosts):
            return JSONResponse(
                status_code=421, content={"error": "misdirected", "message": "Host not allowed."}
            )
        try:
            if proposals is None:
                raise ProposalsUnavailable("Change proposals are not configured on this gateway.")
            return await gateway.execute(
                request.headers, str(uuid.uuid4()), tool, arguments, action
            )
        except OdooError as error:
            return JSONResponse(
                status_code=HTTP_STATUS.get(error.code, 400),
                content={"error": error.code, "message": str(error)},
            )

    @router.get("/pending")
    async def pending(request: Request, limit: int | None = None) -> Any:
        """Pending proposals by other people, on records you can read, with live values."""
        return await respond(
            request,
            "approvals.pending",
            {"limit": limit},
            lambda session: proposals.pending_for(session, limit),
        )

    @router.post("/{proposal_id}/approve")
    async def approve(proposal_id: int, request: Request, body: DecisionBody | None = None) -> Any:
        """Approve a proposal by someone else; the change runs in Odoo with your rights."""
        note = body.note if body else None
        return await respond(
            request,
            "approvals.approve",
            {"proposal_id": proposal_id, "note": note},
            lambda session: proposals.approve(session, proposal_id, note),
        )

    @router.post("/{proposal_id}/reject")
    async def reject(proposal_id: int, request: Request, body: DecisionBody | None = None) -> Any:
        """Reject a proposal, or withdraw your own."""
        note = body.note if body else None
        return await respond(
            request,
            "approvals.reject",
            {"proposal_id": proposal_id, "note": note},
            lambda session: proposals.reject(session, proposal_id, note),
        )

    return router
