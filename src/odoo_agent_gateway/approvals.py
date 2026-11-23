"""The approval API (ADR 0012): where a different person decides on proposals.

It is deliberately not an MCP tool. It uses the same Gateway path as the tools (rate limit,
credentials checked by Odoo, audit with fail-closed), and the approver's own credentials.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from odoo_agent_gateway.gateway import Gateway
from odoo_agent_gateway.http_api import call_through_gateway, host_allowed  # noqa: F401
from odoo_agent_gateway.odoo import OdooSession
from odoo_agent_gateway.proposal_store import ProposalsUnavailable


class DecisionBody(BaseModel):
    note: str | None = None


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
        async def run(session: OdooSession) -> Any:
            if proposals is None:
                raise ProposalsUnavailable("Change proposals are not configured on this gateway.")
            return await action(session)

        return await call_through_gateway(gateway, request, allowed_hosts, tool, arguments, run)

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
