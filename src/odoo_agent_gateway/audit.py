"""Audit log of every tool call (ADR 0008). Credentials and returned data are never stored."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import asyncpg

from odoo_agent_gateway.migrations import apply_migrations
from odoo_agent_gateway.odoo import OdooError

ARGUMENTS_LIMIT = 4000


class AuditUnavailable(OdooError):
    code = "audit_unavailable"


@dataclass(frozen=True)
class AuditEvent:
    request_id: str | None
    login: str | None
    odoo_uid: int | None
    tool: str
    arguments: dict[str, Any]
    outcome: str
    result_count: int | None
    duration_ms: int
    trace_id: str | None = None


class AuditSink(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def record(self, event: AuditEvent) -> None: ...


def audit_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Arguments as JSON-safe data, cut to a preview when they are too large to keep whole."""
    text = json.dumps(arguments, default=str, ensure_ascii=False)
    if len(text) <= ARGUMENTS_LIMIT:
        return json.loads(text)
    return {"truncated": True, "preview": text[:ARGUMENTS_LIMIT]}


@dataclass
class MemoryAuditSink:
    """Keeps events in a list. For tests; `available=False` simulates a database outage."""

    available: bool = True
    events: list[AuditEvent] = field(default_factory=list)

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def record(self, event: AuditEvent) -> None:
        if not self.available:
            raise AuditUnavailable("The audit log is unavailable, so no data can be returned.")
        self.events.append(event)


class PostgresAuditSink:
    """Writes events to the gateway's PostgreSQL. Applies the schema on start."""

    def __init__(self, dsn: str, timeout: float = 10.0) -> None:
        self._dsn = dsn
        self._timeout = timeout
        self._pool: asyncpg.Pool | None = None

    def __repr__(self) -> str:
        return "PostgresAuditSink()"  # the DSN contains a password

    async def start(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=5, timeout=self._timeout
            )
            async with self._pool.acquire() as connection:
                await apply_migrations(connection)
        except (OSError, asyncpg.PostgresError, TimeoutError) as error:
            raise AuditUnavailable("The audit database could not be reached.") from error

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def record(self, event: AuditEvent) -> None:
        if self._pool is None:
            raise AuditUnavailable("The audit log is not started.")
        try:
            await self._pool.execute(
                """
                insert into audit_log (request_id, login, odoo_uid, tool, arguments, outcome,
                                       result_count, duration_ms, trace_id)
                values ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
                """,
                event.request_id,
                event.login,
                event.odoo_uid,
                event.tool,
                json.dumps(audit_arguments(event.arguments), ensure_ascii=False),
                event.outcome,
                event.result_count,
                event.duration_ms,
                event.trace_id,
                timeout=self._timeout,
            )
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError, TimeoutError) as error:
            raise AuditUnavailable(
                "The audit log is unavailable, so no data can be returned."
            ) from error
