"""The audit sink against the gateway's real PostgreSQL (pgvector image from Docker Compose).

Run with:  pytest -m integration
Reads GATEWAY_DATABASE_URL from the environment or from `.env.demo-keys`.
"""

import os
import uuid
from pathlib import Path

import asyncpg
import pytest

from odoo_agent_gateway.audit import AuditEvent, AuditUnavailable, PostgresAuditSink

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"


def database_url() -> str:
    if url := os.environ.get("GATEWAY_DATABASE_URL"):
        return url
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("GATEWAY_DATABASE_URL="):
                return line.split("=", 1)[1]
    pytest.skip("No gateway database: run scripts/demo/setup_demo.py first.")


@pytest.fixture
async def sink():
    audit = PostgresAuditSink(database_url())
    await audit.start()
    yield audit
    await audit.close()


def event(request_id: str) -> AuditEvent:
    return AuditEvent(
        request_id=request_id,
        login="ana",
        odoo_uid=8,
        tool="search_records",
        arguments={"model": "sale.order", "limit": 5},
        outcome="ok",
        result_count=2,
        duration_ms=15,
    )


async def test_schema_can_be_applied_again_on_every_start():
    for _ in range(2):
        audit = PostgresAuditSink(database_url())
        await audit.start()
        await audit.close()


async def test_an_event_is_stored_with_all_its_fields(sink):
    request_id = f"test-{uuid.uuid4()}"

    await sink.record(event(request_id))

    connection = await asyncpg.connect(database_url())
    try:
        row = await connection.fetchrow("select * from audit_log where request_id = $1", request_id)
    finally:
        await connection.close()
    assert row["login"] == "ana"
    assert row["odoo_uid"] == 8
    assert row["tool"] == "search_records"
    assert row["outcome"] == "ok"
    assert row["result_count"] == 2
    assert row["duration_ms"] == 15
    assert row["occurred_at"] is not None


@pytest.mark.parametrize(
    "statement",
    [
        "update audit_log set outcome = 'ok' where request_id = $1",
        "delete from audit_log where request_id = $1",
    ],
)
async def test_rows_cannot_be_changed_or_deleted(sink, statement):
    request_id = f"test-{uuid.uuid4()}"
    await sink.record(event(request_id))

    connection = await asyncpg.connect(database_url())
    try:
        with pytest.raises(asyncpg.exceptions.RaiseError, match="append-only"):
            await connection.execute(statement, request_id)
    finally:
        await connection.close()


async def test_the_table_cannot_be_truncated(sink):
    connection = await asyncpg.connect(database_url())
    try:
        with pytest.raises(asyncpg.exceptions.RaiseError, match="append-only"):
            await connection.execute("truncate audit_log")
    finally:
        await connection.close()


async def test_an_unreachable_database_is_reported_as_unavailable():
    audit = PostgresAuditSink("postgresql://nobody:nothing@127.0.0.1:1/none", timeout=2)

    with pytest.raises(AuditUnavailable):
        await audit.start()
