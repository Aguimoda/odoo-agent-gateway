from pathlib import Path

import pytest

from odoo_agent_gateway.indexer import Indexer, chunk_markdown
from odoo_agent_gateway.odoo import InvalidRequest

pytestmark = pytest.mark.anyio


class FakeEmbedder:
    dimension = 3

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, texts):
        self.texts.extend(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeStore:
    def __init__(self) -> None:
        self.documents: dict[str, list] = {}
        self.records: dict[tuple[str, str, int], object] = {}

    async def replace_document(self, doc_path, chunks):
        self.documents[doc_path] = chunks

    async def prune_documents(self, keep_paths):
        removed = [p for p in self.documents if p not in keep_paths]
        for path in removed:
            del self.documents[path]
        return len(removed)

    async def record_hashes(self, model, field):
        return {k[2]: e.content_hash for k, e in self.records.items() if k[:2] == (model, field)}

    async def upsert_record(self, entry):
        self.records[(entry.model, entry.field, entry.record_id)] = entry

    async def prune_records(self, model, field, keep_ids):
        doomed = [k for k in self.records if k[:2] == (model, field) and k[2] not in keep_ids]
        for key in doomed:
            del self.records[key]
        return len(doomed)


class FakeOdoo:
    """The indexer's view of Odoo: rows per model, or an exception for missing models."""

    def __init__(self, rows: dict) -> None:
        self.uid = 99
        self.rows = rows

    async def call(self, model, method, args=None, kwargs=None):
        assert method == "search_read"
        rows = self.rows.get(model)
        if isinstance(rows, Exception):
            raise rows
        offset, limit = kwargs.get("offset", 0), kwargs["limit"]
        return (rows or [])[offset : offset + limit]


# --- chunking ------------------------------------------------------------------------------


def test_markdown_is_split_by_headings_with_their_titles():
    text = (
        "# Returns\n\nIntro line.\n\n## How to register\n\nGo to Sales.\n\n## Refunds\n\nIn 5 days."
    )

    chunks = chunk_markdown(text, "returns.md")

    assert [title for title, _ in chunks] == [
        "Returns",
        "Returns > How to register",
        "Returns > Refunds",
    ]
    assert chunks[1][1] == "Go to Sales."


def test_long_sections_are_split_on_paragraphs():
    paragraphs = "\n\n".join(f"Paragraph {i} " + "x" * 300 for i in range(5))

    chunks = chunk_markdown(f"# Policy\n\n{paragraphs}", "policy.md", max_chars=800)

    assert len(chunks) > 1
    assert all(len(content) <= 800 for _, content in chunks)


def test_a_file_without_headings_uses_its_name_as_title():
    assert chunk_markdown("Just text.", "notes.md") == [("notes", "Just text.")]


# --- documents -----------------------------------------------------------------------------


async def test_documents_are_indexed_and_deleted_files_are_pruned(tmp_path: Path):
    (tmp_path / "returns.md").write_text("# Returns\n\nWithin 30 days.", encoding="utf-8")
    store, embedder = FakeStore(), FakeEmbedder()
    store.documents["old.md"] = []
    indexer = Indexer(store, embedder, FakeOdoo({}), sources=())

    stats = await indexer.index_documents(tmp_path)

    assert list(store.documents) == ["returns.md"]
    (chunk,) = store.documents["returns.md"]
    assert (chunk.title, chunk.content, chunk.chunk_index) == ("Returns", "Within 30 days.", 0)
    assert stats == {"files": 1, "chunks": 1, "removed_files": 1}


# --- records -------------------------------------------------------------------------------


def odoo_rows():
    return {
        "sale.order": [
            {
                "id": 23,
                "note": "<p>Confidential: 30% discount for Acme</p>",
                "display_name": "S00023",
            },
            {"id": 24, "note": False, "display_name": "S00024"},
        ]
    }


async def test_records_are_indexed_as_references_without_names_or_text():
    store, embedder = FakeStore(), FakeEmbedder()
    indexer = Indexer(store, embedder, FakeOdoo(odoo_rows()), sources=(("sale.order", "note"),))

    stats = await indexer.index_records()

    entry = store.records[("sale.order", "note", 23)]
    assert entry.title == "sale.order:23"
    assert not hasattr(entry, "content")
    assert "Confidential: 30% discount for Acme" in embedder.texts[0]  # used only for the vector
    assert ("sale.order", "note", 24) not in store.records  # empty note skipped
    assert stats["sale.order.note"] == {"indexed": 1, "unchanged": 0, "removed": 0}


async def test_unchanged_records_are_not_embedded_again_and_removed_ones_are_pruned():
    store, embedder = FakeStore(), FakeEmbedder()
    sources = (("sale.order", "note"),)
    await Indexer(store, embedder, FakeOdoo(odoo_rows()), sources=sources).index_records()
    store.records[("sale.order", "note", 99)] = store.records[("sale.order", "note", 23)]
    embedder.texts.clear()

    stats = await Indexer(store, embedder, FakeOdoo(odoo_rows()), sources=sources).index_records()

    assert embedder.texts == []
    assert stats["sale.order.note"] == {"indexed": 0, "unchanged": 1, "removed": 1}


async def test_models_that_are_not_installed_are_skipped():
    store = FakeStore()
    odoo = FakeOdoo({"crm.lead": InvalidRequest("Object crm.lead doesn't exist")})
    indexer = Indexer(store, FakeEmbedder(), odoo, sources=(("crm.lead", "description"),))

    stats = await indexer.index_records()

    assert stats["crm.lead.description"] == {"skipped": "model not available"}


async def test_records_are_read_in_pages():
    rows = {
        "res.partner": [
            {"id": i, "comment": f"note {i}", "display_name": f"P{i}"} for i in range(1, 8)
        ]
    }
    store = FakeStore()
    indexer = Indexer(
        store, FakeEmbedder(), FakeOdoo(rows), sources=(("res.partner", "comment"),), page_size=3
    )

    await indexer.index_records()

    assert len(store.records) == 7


def test_html_comments_are_not_indexed():
    text = "# Returns\n\n<!-- Demo handbook. Fictional content. -->\n\nWithin 30 days."

    assert chunk_markdown(text, "returns.md") == [("Returns", "Within 30 days.")]
