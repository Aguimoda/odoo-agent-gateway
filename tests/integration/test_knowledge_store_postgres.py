"""The vector index against the gateway's real PostgreSQL with pgvector."""

import os
import uuid
from pathlib import Path

import asyncpg
import pytest

from odoo_agent_gateway.embeddings import DIMENSION, FastEmbedEmbedder
from odoo_agent_gateway.knowledge_store import (
    DocumentChunk,
    PostgresKnowledgeStore,
    RecordEntry,
)

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


def unit_vector(position: int) -> list[float]:
    vector = [0.0] * DIMENSION
    vector[position] = 1.0
    return vector


@pytest.fixture
async def store():
    knowledge = PostgresKnowledgeStore(database_url())
    await knowledge.start()
    yield knowledge
    await knowledge.close()


@pytest.fixture
def model_name():
    """A throwaway model name per test, removed afterwards."""
    name = f"test.m{uuid.uuid4().hex[:10]}"
    yield name

    async def cleanup():
        connection = await asyncpg.connect(database_url())
        try:
            await connection.execute(
                "delete from knowledge_chunks where model = $1 or doc_path like $2",
                name,
                f"{name}/%",
            )
        finally:
            await connection.close()

    import anyio

    anyio.run(cleanup)


def entry(model: str, record_id: int, position: int, digest: str = "h1") -> RecordEntry:
    return RecordEntry(
        model, record_id, "note", f"Record {record_id}", digest, unit_vector(position)
    )


async def test_records_are_stored_as_vectors_without_text(store, model_name):
    await store.upsert_record(entry(model_name, 1, 10))

    connection = await asyncpg.connect(database_url())
    try:
        row = await connection.fetchrow(
            "select content, title from knowledge_chunks where model = $1", model_name
        )
    finally:
        await connection.close()
    assert row["content"] is None
    assert row["title"] == "Record 1"


async def test_the_database_refuses_record_text_even_if_code_tried(store, model_name):
    connection = await asyncpg.connect(database_url())
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                insert into knowledge_chunks
                  (kind, title, model, record_id, field, content, content_hash, embedding)
                values ('record', 't', $1, 1, 'note', 'secret text', 'h', $2::vector)
                """,
                model_name,
                "[" + ",".join(["0"] * (DIMENSION - 1) + ["1"]) + "]",
            )
    finally:
        await connection.close()


async def test_search_returns_the_nearest_first(store, model_name):
    await store.upsert_record(entry(model_name, 1, 20))
    await store.upsert_record(entry(model_name, 2, 21))

    results = [c for c in await store.search(unit_vector(21), 50) if c.model == model_name]

    assert results[0].record_id == 2
    assert results[0].score == pytest.approx(1.0, abs=1e-4)
    assert results[0].content is None


async def test_upsert_replaces_the_vector_of_an_existing_record(store, model_name):
    await store.upsert_record(entry(model_name, 1, 30, "old"))
    await store.upsert_record(entry(model_name, 1, 31, "new"))

    assert await store.record_hashes(model_name, "note") == {1: "new"}


async def test_prune_removes_records_that_no_longer_exist(store, model_name):
    for record_id in (1, 2, 3):
        await store.upsert_record(entry(model_name, record_id, 40 + record_id))

    removed = await store.prune_records(model_name, "note", keep_ids=[2])

    assert removed == 2
    assert set(await store.record_hashes(model_name, "note")) == {2}


async def test_documents_keep_their_text_and_are_replaced_whole(store, model_name):
    path = f"{model_name}/handbook.md"
    first = [
        DocumentChunk(path, i, "Returns", f"v1 part {i}", "h", unit_vector(50 + i)) for i in (0, 1)
    ]
    second = [DocumentChunk(path, 0, "Returns", "v2", "h2", unit_vector(60))]

    await store.replace_document(path, first)
    await store.replace_document(path, second)

    results = [c for c in await store.search(unit_vector(60), 50) if c.doc_path == path]
    assert [(c.chunk_index, c.content) for c in results] == [(0, "v2")]


async def test_the_local_model_matches_spanish_questions_to_english_passages():
    embedder = FastEmbedEmbedder(cache_dir=os.environ.get("GATEWAY_MODEL_CACHE", ".cache/models"))
    passages = [
        "Returns are accepted within 30 days if the product is unused.",
        "Shipping to the Canary Islands takes 5 to 7 working days.",
    ]
    questions = ["¿Cómo se registra una devolución?", "¿Cuánto tarda un envío a Canarias?"]

    p_vectors = await embedder.embed(passages)
    q_vectors = await embedder.embed(questions)

    for index, question in enumerate(q_vectors):
        scores = [
            sum(a * b for a, b in zip(question, passage, strict=True)) for passage in p_vectors
        ]
        assert scores.index(max(scores)) == index
    assert len(p_vectors[0]) == DIMENSION
