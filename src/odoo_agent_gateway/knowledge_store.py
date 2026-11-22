"""Vector index in the gateway's PostgreSQL (pgvector). See ADR 0011.

Documents (the company handbook) are stored with their text. Odoo records are stored only as
a vector plus a reference; the database itself refuses record text (knowledge_record_shape).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import asyncpg

from odoo_agent_gateway import tracing
from odoo_agent_gateway.migrations import apply_migrations
from odoo_agent_gateway.odoo import OdooError


class KnowledgeUnavailable(OdooError):
    code = "knowledge_unavailable"


@dataclass(frozen=True)
class DocumentChunk:
    doc_path: str
    chunk_index: int
    title: str
    content: str
    content_hash: str
    vector: list[float]


@dataclass(frozen=True)
class RecordEntry:
    model: str
    record_id: int
    field: str
    title: str
    content_hash: str
    vector: list[float]


@dataclass(frozen=True)
class Candidate:
    kind: str  # "document" or "record"
    title: str
    score: float
    doc_path: str | None = None
    chunk_index: int | None = None
    content: str | None = None  # documents only
    model: str | None = None
    record_id: int | None = None
    field: str | None = None


class KnowledgeStore(Protocol):
    async def search(self, vector: list[float], limit: int) -> list[Candidate]: ...


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"


class PostgresKnowledgeStore:
    def __init__(self, dsn: str, timeout: float = 10.0) -> None:
        self._dsn = dsn
        self._timeout = timeout
        self._pool: asyncpg.Pool | None = None

    def __repr__(self) -> str:
        return "PostgresKnowledgeStore()"  # the DSN contains a password

    async def start(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=5, timeout=self._timeout
            )
            async with self._pool.acquire() as connection:
                await apply_migrations(connection)
        except (OSError, asyncpg.PostgresError, TimeoutError) as error:
            raise KnowledgeUnavailable("The knowledge index could not be reached.") from error

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _ready(self) -> asyncpg.Pool:
        if self._pool is None:
            raise KnowledgeUnavailable("The knowledge index is not started.")
        return self._pool

    async def search(self, vector: list[float], limit: int) -> list[Candidate]:
        with tracing.span("knowledge.index_search", **{"knowledge.limit": limit}):
            return await self._search(vector, limit)

    async def _search(self, vector: list[float], limit: int) -> list[Candidate]:
        try:
            rows = await self._ready().fetch(
                """
                select kind, title, doc_path, chunk_index, content, model, record_id, field,
                       1 - (embedding <=> $1::vector) as score
                from knowledge_chunks
                order by embedding <=> $1::vector
                limit $2
                """,
                vector_literal(vector),
                limit,
                timeout=self._timeout,
            )
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError, TimeoutError) as error:
            raise KnowledgeUnavailable("The knowledge index is unavailable.") from error
        return [
            Candidate(
                kind=row["kind"],
                title=row["title"],
                score=float(row["score"]),
                doc_path=row["doc_path"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                model=row["model"],
                record_id=row["record_id"],
                field=row["field"],
            )
            for row in rows
        ]

    async def replace_document(self, doc_path: str, chunks: list[DocumentChunk]) -> None:
        async with self._ready().acquire() as connection, connection.transaction():
            await connection.execute(
                "delete from knowledge_chunks where kind = 'document' and doc_path = $1", doc_path
            )
            await connection.executemany(
                """
                insert into knowledge_chunks
                  (kind, title, doc_path, chunk_index, content, content_hash, embedding)
                values ('document', $1, $2, $3, $4, $5, $6::vector)
                """,
                [
                    (
                        c.title,
                        c.doc_path,
                        c.chunk_index,
                        c.content,
                        c.content_hash,
                        vector_literal(c.vector),
                    )
                    for c in chunks
                ],
            )

    async def prune_documents(self, keep_paths: list[str]) -> int:
        result = await self._ready().execute(
            "delete from knowledge_chunks where kind = 'document' and not (doc_path = any($1))",
            keep_paths,
        )
        return int(result.split()[-1])

    async def record_hashes(self, model: str, field: str) -> dict[int, str]:
        rows = await self._ready().fetch(
            """
            select record_id, content_hash from knowledge_chunks
            where kind = 'record' and model = $1 and field = $2
            """,
            model,
            field,
        )
        return {row["record_id"]: row["content_hash"] for row in rows}

    async def upsert_record(self, entry: RecordEntry) -> None:
        await self._ready().execute(
            """
            insert into knowledge_chunks
              (kind, title, model, record_id, field, content_hash, embedding)
            values ('record', $1, $2, $3, $4, $5, $6::vector)
            on conflict (model, record_id, field) where kind = 'record'
            do update set title = excluded.title, content_hash = excluded.content_hash,
                          embedding = excluded.embedding, indexed_at = now()
            """,
            entry.title,
            entry.model,
            entry.record_id,
            entry.field,
            entry.content_hash,
            vector_literal(entry.vector),
        )

    async def prune_records(self, model: str, field: str, keep_ids: list[int]) -> int:
        result = await self._ready().execute(
            """
            delete from knowledge_chunks
            where kind = 'record' and model = $1 and field = $2 and not (record_id = any($3))
            """,
            model,
            field,
            keep_ids,
        )
        return int(result.split()[-1])
