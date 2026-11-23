"""Conversations with the assistant (ADR 0016), in the gateway's PostgreSQL.

Every read and delete is filtered by the owner's Odoo user id in SQL, so a conversation that
is not yours looks exactly like one that does not exist. Tool results are never stored.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg

from odoo_agent_gateway.migrations import apply_migrations
from odoo_agent_gateway.odoo import OdooError, RecordNotFound

TITLE_LENGTH = 80


class ConversationsUnavailable(OdooError):
    code = "conversations_unavailable"


@dataclass(frozen=True)
class Conversation:
    id: uuid.UUID
    owner_uid: int
    owner_login: str
    title: str
    created_at: datetime
    updated_at: datetime

    def public(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class Message:
    id: int
    at: datetime
    role: str
    content: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    status: str = "complete"
    error_kind: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "at": self.at.isoformat(),
            "role": self.role,
            "content": self.content,
            "tools": self.tools,
            "model": self.model,
            "status": self.status,
            "error": self.error_kind,
        }


def title_from(text: str) -> str:
    title = " ".join((text or "").split())
    return title if len(title) <= TITLE_LENGTH else title[: TITLE_LENGTH - 1].rstrip() + "…"


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise RecordNotFound("There is no conversation with that id.") from None


_CONVERSATION = "id, owner_uid, owner_login, title, created_at, updated_at"
_MESSAGE = "id, at, role, content, tools, model, status, error_kind"


def _message(row: asyncpg.Record) -> Message:
    values = dict(row)
    values["tools"] = json.loads(values["tools"])
    return Message(**values)


class PostgresConversationStore:
    def __init__(self, dsn: str, timeout: float = 10.0) -> None:
        self._dsn = dsn
        self._timeout = timeout
        self._pool: asyncpg.Pool | None = None

    def __repr__(self) -> str:
        return "PostgresConversationStore()"  # the DSN contains a password

    async def start(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=5, timeout=self._timeout
            )
            async with self._pool.acquire() as connection:
                await apply_migrations(connection)
        except (OSError, asyncpg.PostgresError, TimeoutError) as error:
            raise ConversationsUnavailable(
                "The conversations database could not be reached."
            ) from error

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _ready(self) -> asyncpg.Pool:
        if self._pool is None:
            raise ConversationsUnavailable("The conversations store is not started.")
        return self._pool

    async def create(self, owner_uid: int, owner_login: str, title: str) -> Conversation:
        row = await self._ready().fetchrow(
            f"insert into conversations (owner_uid, owner_login, title) values ($1, $2, $3) "
            f"returning {_CONVERSATION}",
            owner_uid,
            owner_login,
            title_from(title) or "New conversation",
        )
        return Conversation(**dict(row))

    async def get(self, conversation_id: str, owner_uid: int) -> Conversation:
        row = await self._ready().fetchrow(
            f"select {_CONVERSATION} from conversations where id = $1 and owner_uid = $2",
            parse_id(conversation_id),
            owner_uid,
        )
        if row is None:
            raise RecordNotFound("There is no conversation with that id.")
        return Conversation(**dict(row))

    async def list_for(self, owner_uid: int, limit: int = 50) -> list[Conversation]:
        rows = await self._ready().fetch(
            f"select {_CONVERSATION} from conversations where owner_uid = $1 "
            "order by updated_at desc, id limit $2",
            owner_uid,
            limit,
        )
        return [Conversation(**dict(row)) for row in rows]

    async def messages(
        self, conversation_id: str, owner_uid: int, limit: int = 200
    ) -> list[Message]:
        conversation = await self.get(conversation_id, owner_uid)
        rows = await self._ready().fetch(
            f"select {_MESSAGE} from ("
            f"  select {_MESSAGE} from conversation_messages where conversation_id = $1 "
            "  order by id desc limit $2"
            ") latest order by id",
            conversation.id,
            limit,
        )
        return [_message(row) for row in rows]

    async def add_message(
        self,
        conversation: Conversation,
        role: str,
        content: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        status: str = "complete",
        error_kind: str | None = None,
    ) -> Message:
        async with self._ready().acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                "insert into conversation_messages "
                "(conversation_id, role, content, tools, model, status, error_kind) "
                f"values ($1, $2, $3, $4::jsonb, $5, $6, $7) returning {_MESSAGE}",
                conversation.id,
                role,
                content,
                json.dumps(tools or [], ensure_ascii=False),
                model,
                status,
                error_kind,
            )
            await connection.execute(
                "update conversations set updated_at = now() where id = $1", conversation.id
            )
        return _message(row)

    async def delete(self, conversation_id: str, owner_uid: int) -> bool:
        result = await self._ready().execute(
            "delete from conversations where id = $1 and owner_uid = $2",
            parse_id(conversation_id),
            owner_uid,
        )
        return result.endswith(" 1")

    async def purge(self, retention_days: int) -> int:
        """Delete conversations untouched for longer than the retention period."""
        result = await self._ready().execute(
            "delete from conversations where updated_at < now() - make_interval(days => $1)",
            retention_days,
        )
        return int(result.split()[-1])
