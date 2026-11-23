"""What every HTTP API of the gateway does around a call: host check, Gateway path, errors."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from odoo_agent_gateway.gateway import Gateway
from odoo_agent_gateway.odoo import OdooError, OdooSession

HTTP_STATUS = {
    "unauthenticated": 401,
    "forbidden": 403,
    "four_eyes": 403,
    "not_found": 404,
    "conflict": 409,
    "model_unavailable": 409,
    "invalid_request": 422,
    "rate_limited": 429,
    "internal_error": 500,
    "odoo_unavailable": 502,
    "audit_unavailable": 503,
    "proposals_unavailable": 503,
    "providers_unavailable": 503,
    "conversations_unavailable": 503,
}


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


def error_response(error: OdooError) -> JSONResponse:
    return JSONResponse(
        status_code=HTTP_STATUS.get(error.code, 400),
        content={"error": error.code, "message": str(error)},
    )


async def call_through_gateway(
    gateway: Gateway,
    request: Request,
    allowed_hosts: tuple[str, ...],
    tool: str,
    arguments: dict[str, Any],
    action: Callable[[OdooSession], Awaitable[Any]],
) -> Any:
    """Run `action` as the caller on the shared Gateway path, or answer with an error."""
    if not host_allowed(request.headers.get("host", ""), allowed_hosts):
        return JSONResponse(
            status_code=421, content={"error": "misdirected", "message": "Host not allowed."}
        )
    try:
        return await gateway.execute(request.headers, str(uuid.uuid4()), tool, arguments, action)
    except OdooError as error:
        return error_response(error)
