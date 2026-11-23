"""Conversations against the gateway's real PostgreSQL: privacy, history and retention."""

import os
from pathlib import Path

import asyncpg
import pytest

from odoo_agent_gateway.conversation_store import PostgresConversationStore, title_from
from odoo_agent_gateway.odoo import RecordNotFound

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"
ANA, LUIS = 900_001, 900_002  # test uids, far from the demo's real ones


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
    conversations = PostgresConversationStore(database_url())
    await conversations.start()
    yield conversations
    await conversations.close()


async def test_history_in_order_with_tools_but_no_results(store):
    chat = await store.create(ANA, "ana", "¿Cuál es el plazo de envío?")
    await store.add_message(chat, "user", "¿Cuál es el plazo de envío?")
    tools = [
        {
            "name": "search_knowledge",
            "arguments": {"query": "plazo de envío"},
            "ok": True,
            "count": 2,
        }
    ]
    await store.add_message(
        chat,
        "assistant",
        "Son 3 días (shipping.md).",
        tools=tools,
        model="groq/openai/gpt-oss-120b",
    )
    messages = await store.messages(str(chat.id), ANA)
    assert [m.role for m in messages] == ["user", "assistant"]
    empty = await store.create(ANA, "ana", "")
    listed = [c.id for c in await store.list_for(ANA)]
    assert chat.id in listed and empty.id not in listed  # nothing said yet: not listed
    await store.delete(str(empty.id), ANA)
    assert messages[1].tools == tools and messages[1].model == "groq/openai/gpt-oss-120b"
    assert (await store.list_for(ANA))[0].id == chat.id
    await store.delete(str(chat.id), ANA)


async def test_someone_else_s_conversation_does_not_exist(store):
    """Scenario: conversaciones privadas."""
    chat = await store.create(ANA, "ana", "privado")
    for action in (
        store.get(str(chat.id), LUIS),
        store.messages(str(chat.id), LUIS),
    ):
        with pytest.raises(RecordNotFound):
            await action
    assert not await store.delete(str(chat.id), LUIS)
    assert all(c.id != chat.id for c in await store.list_for(LUIS))
    assert await store.delete(str(chat.id), ANA)
    with pytest.raises(RecordNotFound):
        await store.get(str(chat.id), ANA)


async def test_bad_ids_are_not_found(store):
    with pytest.raises(RecordNotFound):
        await store.get("not-a-uuid", ANA)


async def test_deleting_removes_the_messages(store):
    chat = await store.create(ANA, "ana", "borrar")
    await store.add_message(chat, "user", "hola")
    await store.delete(str(chat.id), ANA)
    connection = await asyncpg.connect(database_url())
    try:
        left = await connection.fetchval(
            "select count(*) from conversation_messages where conversation_id = $1", chat.id
        )
    finally:
        await connection.close()
    assert left == 0


async def test_retention_purges_old_conversations_only(store):
    old = await store.create(ANA, "ana", "vieja")
    fresh = await store.create(ANA, "ana", "nueva")
    connection = await asyncpg.connect(database_url())
    try:
        await connection.execute(
            "update conversations set updated_at = now() - interval '31 days' where id = $1",
            old.id,
        )
    finally:
        await connection.close()
    assert await store.purge(30) >= 1
    with pytest.raises(RecordNotFound):
        await store.get(str(old.id), ANA)
    assert (await store.get(str(fresh.id), ANA)).id == fresh.id
    await store.delete(str(fresh.id), ANA)


def test_titles_are_short_and_single_line():
    assert title_from("  hola\n  mundo ") == "hola mundo"
    long = title_from("x" * 200)
    assert len(long) == 80 and long.endswith("…")
