"""The proposals table against the gateway's real PostgreSQL: storage and its guarantees."""

import os
import uuid
from pathlib import Path

import asyncpg
import pytest

from odoo_agent_gateway.proposal_store import Decision, PostgresProposalStore

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"


def missing(reason: str):
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def database_url() -> str:
    if url := os.environ.get("GATEWAY_DATABASE_URL"):
        return url
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("GATEWAY_DATABASE_URL="):
                return line.split("=", 1)[1]
    missing("No gateway database: run scripts/demo/setup_demo.py first.")


@pytest.fixture
async def store():
    proposals = PostgresProposalStore(database_url())
    await proposals.start()
    yield proposals
    await proposals.close()


async def new_proposal(store, **changes):
    values = dict(
        proposer_login="ana",
        proposer_uid=8,
        model=f"test.m{uuid.uuid4().hex[:8]}",
        record_id=1,
        changes={"phone": "+34 600 000 000"},
        before_hash="abc",
        reason="Customer called to update the phone number.",
    )
    values.update(changes)
    return await store.create(**values)


async def execute(sql: str, *args):
    connection = await asyncpg.connect(database_url())
    try:
        return await connection.execute(sql, *args)
    finally:
        await connection.close()


async def test_a_proposal_is_stored_pending_with_its_changes(store):
    proposal = await new_proposal(store)

    loaded = await store.get(proposal.id)

    assert loaded.status == "pending"
    assert loaded.changes == {"phone": "+34 600 000 000"}
    assert loaded.decided_at is None


async def test_a_decision_is_recorded_once_and_is_final(store):
    proposal = await new_proposal(store)

    async def approve(_):
        return Decision("applied")

    decided = await store.decide(
        proposal.id, approve, decider_login="luis", decider_uid=9, note="ok"
    )

    assert (decided.status, decided.decider_login, decided.decision_note) == (
        "applied",
        "luis",
        "ok",
    )
    with pytest.raises(asyncpg.exceptions.RaiseError, match="already decided"):
        await execute("update change_proposals set status = 'pending' where id = $1", proposal.id)


async def test_the_content_of_a_pending_proposal_cannot_change(store):
    proposal = await new_proposal(store)

    with pytest.raises(asyncpg.exceptions.RaiseError, match="cannot change"):
        await execute(
            """update change_proposals set changes = '{"phone": "x"}'::jsonb where id = $1""",
            proposal.id,
        )


@pytest.mark.parametrize(
    "sql", ["delete from change_proposals where id = $1", "truncate change_proposals"]
)
async def test_proposals_cannot_be_deleted_or_truncated(store, sql):
    proposal = await new_proposal(store)

    with pytest.raises(asyncpg.exceptions.RaiseError):
        if "$1" in sql:
            await execute(sql, proposal.id)
        else:
            await execute(sql)


async def test_a_decider_that_returns_none_leaves_the_proposal_pending(store):
    proposal = await new_proposal(store)

    async def no_decision(_):
        return None

    result = await store.decide(
        proposal.id, no_decision, decider_login="ana", decider_uid=8, note=None
    )

    assert result.status == "pending"
    assert (await store.get(proposal.id)).status == "pending"


async def test_a_failing_decider_records_nothing(store):
    proposal = await new_proposal(store)

    async def boom(_):
        raise RuntimeError("Odoo down")

    with pytest.raises(RuntimeError):
        await store.decide(proposal.id, boom, decider_login="luis", decider_uid=9, note=None)
    assert (await store.get(proposal.id)).status == "pending"


async def test_proposals_are_listed_by_proposer_and_pending(store):
    # Proposals can never be deleted, so each run needs a proposer id of its own.
    proposer_uid = 10_000_000 + uuid.uuid4().int % 1_000_000_000
    mine = await new_proposal(store, proposer_uid=proposer_uid)

    assert [p.id for p in await store.list_by_proposer(proposer_uid, None, 10)] == [mine.id]
    assert mine.id in [p.id for p in await store.list_pending(1000)]
    # Filtered in SQL, before the limit: other models and the approver's own are left out.
    assert mine.id in [p.id for p in await store.list_pending(5, models=[mine.model])]
    assert mine.id not in [p.id for p in await store.list_pending(1000, models=["res.partner"])]
    assert mine.id not in [
        p.id for p in await store.list_pending(1000, exclude_proposer_uid=mine.proposer_uid)
    ]


async def test_short_reasons_are_refused_by_the_database(store):
    with pytest.raises(asyncpg.CheckViolationError):
        await new_proposal(store, reason="too short")
