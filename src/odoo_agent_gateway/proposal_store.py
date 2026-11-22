"""Storage for change proposals (ADR 0012), in the gateway's PostgreSQL."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from odoo_agent_gateway.migrations import apply_migrations
from odoo_agent_gateway.odoo import OdooError, RecordNotFound


class ProposalsUnavailable(OdooError):
    code = "proposals_unavailable"


@dataclass(frozen=True)
class Proposal:
    id: int
    created_at: datetime
    proposer_login: str
    proposer_uid: int
    model: str
    record_id: int
    changes: dict[str, Any]
    before_hash: str
    reason: str
    status: str = "pending"
    decided_at: datetime | None = None
    decider_login: str | None = None
    decider_uid: int | None = None
    decision_note: str | None = None
    error_code: str | None = None

    def public(self) -> dict[str, Any]:
        """What callers see. The fingerprint stays internal."""
        return {
            "proposal_id": self.id,
            "created_at": self.created_at.isoformat(),
            "proposer": self.proposer_login,
            "model": self.model,
            "record_id": self.record_id,
            "changes": self.changes,
            "reason": self.reason,
            "status": self.status,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by": self.decider_login,
            "decision_note": self.decision_note,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class Decision:
    status: str
    error_code: str | None = None


Decider = Callable[[Proposal], Awaitable[Decision | None]]

_COLUMNS = (
    "id, created_at, proposer_login, proposer_uid, model, record_id, changes, before_hash, "
    "reason, status, decided_at, decider_login, decider_uid, decision_note, error_code"
)


def _row(row: asyncpg.Record) -> Proposal:
    values = dict(row)
    values["changes"] = json.loads(values["changes"])
    return Proposal(**values)


class PostgresProposalStore:
    def __init__(self, dsn: str, timeout: float = 10.0) -> None:
        self._dsn = dsn
        self._timeout = timeout
        self._pool: asyncpg.Pool | None = None

    def __repr__(self) -> str:
        return "PostgresProposalStore()"  # the DSN contains a password

    async def start(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=5, timeout=self._timeout
            )
            async with self._pool.acquire() as connection:
                await apply_migrations(connection)
        except (OSError, asyncpg.PostgresError, TimeoutError) as error:
            raise ProposalsUnavailable("The proposals database could not be reached.") from error

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _ready(self) -> asyncpg.Pool:
        if self._pool is None:
            raise ProposalsUnavailable("The proposals store is not started.")
        return self._pool

    async def create(
        self,
        *,
        proposer_login: str,
        proposer_uid: int,
        model: str,
        record_id: int,
        changes: dict[str, Any],
        before_hash: str,
        reason: str,
    ) -> Proposal:
        row = await self._ready().fetchrow(
            f"""
            insert into change_proposals
              (proposer_login, proposer_uid, model, record_id, changes, before_hash, reason)
            values ($1, $2, $3, $4, $5::jsonb, $6, $7)
            returning {_COLUMNS}
            """,
            proposer_login,
            proposer_uid,
            model,
            record_id,
            json.dumps(changes, ensure_ascii=False),
            before_hash,
            reason,
        )
        return _row(row)

    async def get(self, proposal_id: int) -> Proposal | None:
        row = await self._ready().fetchrow(
            f"select {_COLUMNS} from change_proposals where id = $1", proposal_id
        )
        return _row(row) if row else None

    async def list_by_proposer(
        self, proposer_uid: int, status: str | None, limit: int
    ) -> list[Proposal]:
        rows = await self._ready().fetch(
            f"""
            select {_COLUMNS} from change_proposals
            where proposer_uid = $1 and ($2::text is null or status = $2)
            order by created_at desc, id desc limit $3
            """,
            proposer_uid,
            status,
            limit,
        )
        return [_row(row) for row in rows]

    async def list_pending(self, limit: int) -> list[Proposal]:
        rows = await self._ready().fetch(
            f"""
            select {_COLUMNS} from change_proposals
            where status = 'pending' order by created_at, id limit $1
            """,
            limit,
        )
        return [_row(row) for row in rows]

    async def decide(
        self,
        proposal_id: int,
        decider: Decider,
        *,
        decider_login: str,
        decider_uid: int,
        note: str | None,
    ) -> Proposal:
        """Lock the proposal, let `decider` act (it may write to Odoo), then record its decision.

        The row stays locked while `decider` runs, so two approvers cannot both apply it. If
        `decider` returns None or raises, nothing is recorded and the proposal stays as it was.
        """
        async with self._ready().acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                f"select {_COLUMNS} from change_proposals where id = $1 for update", proposal_id
            )
            if row is None:
                raise RecordNotFound("There is no proposal with that id.")
            proposal = _row(row)
            decision = await decider(proposal)
            if decision is None:
                return proposal
            updated = await connection.fetchrow(
                f"""
                update change_proposals
                set status = $2, decided_at = now(), decider_login = $3, decider_uid = $4,
                    decision_note = $5, error_code = $6
                where id = $1
                returning {_COLUMNS}
                """,
                proposal_id,
                decision.status,
                decider_login,
                decider_uid,
                note,
                decision.error_code,
            )
            return _row(updated)
