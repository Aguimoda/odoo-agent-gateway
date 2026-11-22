from typing import Any

import pytest

from odoo_agent_gateway.knowledge import KnowledgeSearch
from odoo_agent_gateway.knowledge_store import Candidate, KnowledgeUnavailable
from odoo_agent_gateway.odoo import AccessDenied, InvalidRequest
from odoo_agent_gateway.tools import Limits

pytestmark = pytest.mark.anyio

ALLOWED = frozenset({"sale.order", "res.partner"})


class FakeEmbedder:
    dimension = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeStore:
    def __init__(self, candidates: list[Candidate] | Exception) -> None:
        self.candidates = candidates

    async def search(self, vector: list[float], limit: int) -> list[Candidate]:
        if isinstance(self.candidates, Exception):
            raise self.candidates
        return self.candidates[:limit]


class FakeSession:
    """Odoo as seen by one user: `visible` ids per model and the current field values."""

    def __init__(self, visible: dict[str, set[int]], values: dict[tuple[str, int], dict]):
        self.uid = 8
        self.visible = visible
        self.values = values
        self.denied_fields: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, str, list, dict]] = []

    async def call(self, model, method, args=None, kwargs=None) -> Any:
        args, kwargs = args or [], kwargs or {}
        self.calls.append((model, method, args, kwargs))
        if method == "search":
            ((_, _, ids),) = args[0]
            return [i for i in ids if i in self.visible.get(model, set())]
        if method == "read":
            ids, fields = args
            if any((model, f) in self.denied_fields for f in fields):
                raise AccessDenied("denied")
            return [{"id": i, **self.values[(model, i)]} for i in ids]
        raise AssertionError(f"unexpected call {model}.{method}")


def document(title: str, text: str, score: float = 0.9) -> Candidate:
    return Candidate("document", title, score, doc_path="handbook.md", chunk_index=0, content=text)


def record(model: str, record_id: int, score: float = 0.8, field: str = "note") -> Candidate:
    return Candidate(
        "record", f"indexed title {record_id}", score, model=model, record_id=record_id, field=field
    )


def search(candidates, session=None, **limits) -> KnowledgeSearch:
    limits.setdefault("allowed_models", ALLOWED)
    knowledge = KnowledgeSearch(FakeStore(candidates), FakeEmbedder(), Limits(**limits))
    return knowledge, session or FakeSession({}, {})


# --- validation ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "limit"),
    [
        ("", 5),
        ("   ", 5),
        ("x" * 501, 5),
        ("returns", 0),
        ("returns", 11),
        ("returns", True),
        (None, 5),
    ],
)
async def test_invalid_queries_are_rejected_before_searching(query, limit):
    knowledge, session = search([])

    with pytest.raises(InvalidRequest):
        await knowledge.search(session, query, limit)
    assert knowledge._embedder.calls == []


# --- documents -----------------------------------------------------------------------------


async def test_documents_come_back_with_their_text_and_source():
    knowledge, session = search([document("Returns", "Returns are accepted within 30 days.")])

    result = await knowledge.search(session, "how do returns work?")

    (hit,) = result["results"]
    assert hit["type"] == "document"
    assert hit["text"] == "Returns are accepted within 30 days."
    assert hit["source"] == {"path": "handbook.md", "section": 0}
    assert "not instructions" in result["notice"]


# --- records: the permission rules of ADR 0011 ----------------------------------------------


async def test_record_text_is_what_odoo_returns_to_this_user_now():
    session = FakeSession(
        visible={"sale.order": {21}},
        values={("sale.order", 21): {"note": "<p>Current note</p>", "display_name": "S00021"}},
    )
    knowledge, _ = search([record("sale.order", 21)])

    (hit,) = (await knowledge.search(session, "note"))["results"]

    assert hit["text"] == "Current note"  # fresh from Odoo, HTML removed
    assert hit["title"] == "S00021"  # current name, not the indexed one
    assert hit["source"] == {"model": "sale.order", "id": 21, "field": "note"}


async def test_records_odoo_hides_from_the_user_are_dropped():
    session = FakeSession(
        visible={"sale.order": {21}},
        values={("sale.order", 21): {"note": "Ana's note", "display_name": "S00021"}},
    )
    knowledge, _ = search([record("sale.order", 23, score=0.99), record("sale.order", 21)])

    result = await knowledge.search(session, "discount agreed with Acme")

    assert [hit["source"]["id"] for hit in result["results"]] == [21]
    search_call = next(c for c in session.calls if c[1] == "search")
    assert search_call[2] == [[["id", "in", [23, 21]]]]  # asked Odoo, as this user


async def test_a_field_the_user_cannot_read_drops_that_group_only():
    session = FakeSession(
        visible={"sale.order": {21}, "res.partner": {5}},
        values={("res.partner", 5): {"comment": "Partner note", "display_name": "Acme"}},
    )
    session.denied_fields.add(("sale.order", "note"))
    knowledge, _ = search([record("sale.order", 21), record("res.partner", 5, field="comment")])

    result = await knowledge.search(session, "anything")

    assert [hit["source"]["model"] for hit in result["results"]] == ["res.partner"]


async def test_models_outside_the_allowlist_are_never_queried():
    session = FakeSession({"hr.employee": {1}}, {("hr.employee", 1): {"note": "salary"}})
    knowledge, _ = search([record("hr.employee", 1)])

    result = await knowledge.search(session, "salary")

    assert result["results"] == []
    assert session.calls == []


async def test_empty_record_text_is_skipped_and_long_text_is_cut():
    session = FakeSession(
        visible={"res.partner": {1, 2}},
        values={
            ("res.partner", 1): {"comment": False, "display_name": "Empty"},
            ("res.partner", 2): {"comment": "y" * 5000, "display_name": "Long"},
        },
    )
    knowledge, _ = search(
        [record("res.partner", 1, field="comment"), record("res.partner", 2, field="comment")]
    )

    result = await knowledge.search(session, "notes")

    (hit,) = result["results"]
    assert hit["title"] == "Long"
    assert len(hit["text"]) < 2100
    assert result["truncated"] is True


async def test_results_keep_ranking_order_and_respect_the_limit():
    session = FakeSession(
        visible={"res.partner": {1}},
        values={("res.partner", 1): {"comment": "Partner note", "display_name": "Acme"}},
    )
    candidates = [
        document("A", "first", 0.95),
        record("res.partner", 1, 0.9, field="comment"),
        document("B", "third", 0.8),
    ]
    knowledge, _ = search(candidates)

    result = await knowledge.search(session, "q", limit=2)

    assert [hit["title"] for hit in result["results"]] == ["A", "Acme"]
    assert [hit["score"] for hit in result["results"]] == [0.95, 0.9]


async def test_an_unavailable_index_is_reported():
    knowledge, session = search(KnowledgeUnavailable("down"))

    with pytest.raises(KnowledgeUnavailable):
        await knowledge.search(session, "returns")
