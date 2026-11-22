"""The one path every call takes, whatever the channel (MCP tools or the approval API).

Rate limit for the claimed login (ADR 0009), credentials from the request headers checked by
Odoo (ADR 0005), the action itself, then one audit row; no audit row means no answer
(ADR 0008). Errors are raised as gateway errors; each channel turns them into its own format.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx2

from odoo_agent_gateway.audit import AuditEvent, AuditSink
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.odoo import AuthenticationFailed, OdooClient, OdooError, OdooSession
from odoo_agent_gateway.ratelimit import RateLimited, RateLimiter

HttpClientFactory = Callable[[], httpx2.AsyncClient]

LOGIN_HEADER = "x-odoo-login"

logger = logging.getLogger(__name__)


class InternalError(OdooError):
    code = "internal_error"


class OdooProvider:
    """Owns the shared HTTP connection pool to Odoo. Holds no user credentials."""

    def __init__(self, settings: Settings, http_client_factory: HttpClientFactory) -> None:
        self._settings = settings
        self._factory = http_client_factory
        self._http: httpx2.AsyncClient | None = None
        self._client: OdooClient | None = None

    def client(self) -> OdooClient:
        if self._client is None:
            self._http = self._factory()
            self._client = OdooClient(self._settings.odoo_url, self._settings.odoo_db, self._http)
        return self._client

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        self._http = self._client = None


def credentials_from(headers: Mapping[str, str] | None) -> tuple[str, str]:
    """Extract (login, api_key) from request headers, or fail as unauthenticated."""
    headers = {key.lower(): value for key, value in (headers or {}).items()}
    scheme, _, api_key = headers.get("authorization", "").partition(" ")
    login = headers.get(LOGIN_HEADER, "").strip()
    if scheme.lower() != "bearer" or not api_key.strip() or not login:
        raise AuthenticationFailed(
            "Send the Odoo login in X-Odoo-Login and the user's Odoo API key as "
            "'Authorization: Bearer <key>'."
        )
    return login, api_key.strip()


def claimed_login(headers: Mapping[str, str] | None) -> str | None:
    """The login the caller says it is. Unverified: used only for rate limiting and audit."""
    for key, value in (headers or {}).items():
        if key.lower() == LOGIN_HEADER:
            return value.strip() or None
    return None


def result_count(result: Any) -> int | None:
    """How many records, groups, results, models or fields came back, for the audit log."""
    if not isinstance(result, dict):
        return None
    for key in ("records", "results", "groups", "fields", "proposals"):
        if isinstance(result.get(key), list):
            return len(result[key])
    if "record" in result or "proposal_id" in result:
        return 1
    models = result.get("models")
    return len(models) if isinstance(models, (list, dict)) else None


class Gateway:
    def __init__(self, provider: OdooProvider, audit: AuditSink, limiter: RateLimiter) -> None:
        self.provider = provider
        self._audit = audit
        self._limiter = limiter

    async def execute(
        self,
        headers: Mapping[str, str] | None,
        request_id: str | None,
        tool: str,
        arguments: dict[str, Any],
        action: Callable[[OdooSession], Awaitable[Any]],
    ) -> Any:
        started = time.perf_counter()
        login = claimed_login(headers)
        uid: int | None = None
        result: Any = None
        failure: OdooError | None = None
        try:
            if not self._limiter.allow(login):
                raise RateLimited("Too many calls for this login. Try again in a minute.")
            user, api_key = credentials_from(headers)
            session = await self.provider.client().authenticate(user, api_key)
            uid = session.uid
            result = await action(session)
        except OdooError as error:
            failure = error
        except Exception:
            logger.exception("Unexpected error in %s", tool)
            failure = InternalError("Unexpected gateway error.")

        await self._audit.record(  # raises AuditUnavailable: fail closed (ADR 0008)
            AuditEvent(
                request_id=request_id,
                login=login,
                odoo_uid=uid,
                tool=tool,
                arguments={key: value for key, value in arguments.items() if value is not None},
                outcome=failure.code if failure else "ok",
                result_count=None if failure else result_count(result),
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
        )
        if failure:
            raise failure
        return result
