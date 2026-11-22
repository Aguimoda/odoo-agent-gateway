"""Minimal async JSON-RPC client for Odoo's external API.

Every call is made as the authenticated end user (ADR 0002). The user's API key is held
only in memory for the duration of a request and is never included in errors or
representations (ADR 0005).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx2

from odoo_agent_gateway import tracing


class OdooError(Exception):
    """Base class for errors reported to the agent. Messages never contain credentials."""

    code = "odoo_error"


class AuthenticationFailed(OdooError):
    code = "unauthenticated"


class AccessDenied(OdooError):
    code = "forbidden"


class RecordNotFound(OdooError):
    code = "not_found"


class InvalidRequest(OdooError):
    code = "invalid_request"


class OdooUnavailable(OdooError):
    code = "odoo_unavailable"


_MESSAGE_LIMIT = 300

# Odoo exception name -> (gateway error, whether Odoo's own message may be passed on).
# Access errors name the records that were refused, so their message is never forwarded.
_ERROR_MAP: dict[str, tuple[type[OdooError], bool]] = {
    "odoo.exceptions.AccessError": (AccessDenied, False),
    "odoo.exceptions.AccessDenied": (AuthenticationFailed, False),
    "odoo.exceptions.MissingError": (RecordNotFound, False),
    "odoo.exceptions.ValidationError": (InvalidRequest, True),
    "odoo.exceptions.UserError": (InvalidRequest, True),
    "builtins.ValueError": (InvalidRequest, True),
    "builtins.KeyError": (InvalidRequest, True),
    "builtins.TypeError": (InvalidRequest, True),
}

_GENERIC_MESSAGES: dict[type[OdooError], str] = {
    AuthenticationFailed: "The Odoo login or API key was not accepted.",
    AccessDenied: "Odoo denied access to this data for the current user.",
    RecordNotFound: "The record does not exist or is no longer available.",
    InvalidRequest: "Odoo rejected the request as invalid.",
    OdooError: "Odoo returned an unexpected error.",
}


class OdooClient:
    """Talks to one Odoo database. Holds no user credentials itself."""

    def __init__(self, base_url: str, db: str, http: httpx2.AsyncClient) -> None:
        self._endpoint = base_url.rstrip("/") + "/jsonrpc"
        self.db = db
        self._http = http

    def __repr__(self) -> str:
        return f"OdooClient(endpoint={self._endpoint!r}, db={self.db!r})"

    async def authenticate(self, login: str, api_key: str) -> OdooSession:
        login = (login or "").strip()
        if not login or not api_key:
            raise AuthenticationFailed(_GENERIC_MESSAGES[AuthenticationFailed])
        uid = await self._rpc("common", "authenticate", [self.db, login, api_key, {}], api_key)
        if not uid:
            raise AuthenticationFailed(_GENERIC_MESSAGES[AuthenticationFailed])
        return OdooSession(client=self, uid=uid, login=login, api_key=api_key)

    async def _rpc(self, service: str, method: str, args: list[Any], secret: str) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
        }
        # Span attributes name the call only: never the arguments, which hold the key and data.
        is_object = service == "object" and len(args) >= 5
        attributes = {
            "odoo.service": service,
            "odoo.method": args[4] if is_object else method,
            "odoo.model": args[3] if is_object else None,
        }
        with tracing.span("odoo.rpc", **attributes) as span:
            try:
                response = await self._http.post(self._endpoint, json=payload)
                response.raise_for_status()
                body = response.json()
            except (httpx2.HTTPError, ValueError) as exc:
                cause = None if secret in str(exc) else exc
                span.set_attribute("odoo.error", OdooUnavailable.code)
                raise OdooUnavailable(
                    "Odoo could not be reached or returned an invalid response."
                ) from cause
            if "error" in body:
                error = _map_error(body["error"], secret)
                span.set_attribute("odoo.error", error.code)
                raise error
            return body.get("result")


@dataclass(frozen=True)
class OdooSession:
    """An authenticated user. Every call runs with that user's own rights."""

    client: OdooClient
    uid: int
    login: str
    api_key: str = field(repr=False)

    async def call(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Run `model.method(*args, **kwargs)` in Odoo, mirroring `execute_kw` exactly."""
        rpc_args = [self.client.db, self.uid, self.api_key, model, method, args or [], kwargs or {}]
        return await self.client._rpc("object", "execute_kw", rpc_args, self.api_key)


def _map_error(error: dict[str, Any], secret: str) -> OdooError:
    data = error.get("data") or {}
    error_class, forward_message = _ERROR_MAP.get(data.get("name", ""), (OdooError, False))
    message = _GENERIC_MESSAGES[error_class]
    if forward_message:
        odoo_message = str(data.get("message") or "").strip()
        if odoo_message and secret not in odoo_message:
            message = odoo_message[:_MESSAGE_LIMIT]
    return error_class(message)
