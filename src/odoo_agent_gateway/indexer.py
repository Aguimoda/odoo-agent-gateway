"""Builds the knowledge index offline (ADR 0011). Never runs inside the gateway process.

Documents are stored with their text. Records are read with the dedicated `indexer` Odoo
user and stored only as a vector plus a reference: their text is used to compute the vector
and then discarded, and their title is the reference, not their name.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from odoo_agent_gateway.embeddings import Embedder
from odoo_agent_gateway.knowledge_store import DocumentChunk, RecordEntry
from odoo_agent_gateway.odoo import InvalidRequest
from odoo_agent_gateway.textutil import odoo_text
from odoo_agent_gateway.tools import Session

DEFAULT_SOURCES: tuple[tuple[str, str], ...] = (
    ("product.template", "description_sale"),
    ("res.partner", "comment"),
    ("sale.order", "note"),
)
EMBED_TEXT_LIMIT = 2000
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_markdown(text: str, path: str, max_chars: int = 800) -> list[tuple[str, str]]:
    """Split Markdown into (title, content) chunks: one per section, long sections by paragraph.

    A section title is its heading path, for example "Returns > Refunds".
    """
    sections: list[tuple[str, list[str]]] = []
    stack: list[tuple[int, str]] = []
    current: list[str] = []
    title = Path(path).stem

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            sections.append((title, current))
            level, heading = len(match.group(1)), match.group(2)
            stack = [(lvl, txt) for lvl, txt in stack if lvl < level] + [(level, heading)]
            title, current = " > ".join(txt for _, txt in stack), []
        else:
            current.append(line)
    sections.append((title, current))

    chunks: list[tuple[str, str]] = []
    for section_title, lines in sections:
        paragraphs = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
        buffer = ""
        for paragraph in paragraphs:
            candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
            if buffer and len(candidate) > max_chars:
                chunks.append((section_title, buffer))
                buffer = paragraph
            else:
                buffer = candidate
            while len(buffer) > max_chars:
                chunks.append((section_title, buffer[:max_chars]))
                buffer = buffer[max_chars:]
        if buffer:
            chunks.append((section_title, buffer))
    return chunks


class Indexer:
    def __init__(
        self,
        store: Any,
        embedder: Embedder,
        odoo: Session,
        sources: tuple[tuple[str, str], ...] = DEFAULT_SOURCES,
        page_size: int = 200,
        batch_size: int = 64,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._odoo = odoo
        self._sources = sources
        self._page_size = page_size
        self._batch_size = batch_size

    async def index_documents(self, folder: Path) -> dict[str, int]:
        files = sorted(folder.rglob("*.md"))
        paths, chunk_total = [], 0
        for file in files:
            doc_path = file.relative_to(folder).as_posix()
            chunks = chunk_markdown(file.read_text(encoding="utf-8"), doc_path)
            vectors = await self._embedder.embed([f"{title}\n{body}" for title, body in chunks])
            await self._store.replace_document(
                doc_path,
                [
                    DocumentChunk(doc_path, index, title, body, content_hash(body), vector)
                    for index, ((title, body), vector) in enumerate(
                        zip(chunks, vectors, strict=True)
                    )
                ],
            )
            paths.append(doc_path)
            chunk_total += len(chunks)
        removed = await self._store.prune_documents(paths)
        return {"files": len(files), "chunks": chunk_total, "removed_files": removed}

    async def index_records(self) -> dict[str, dict[str, Any]]:
        stats: dict[str, dict[str, Any]] = {}
        for model, field in self._sources:
            try:
                stats[f"{model}.{field}"] = await self._index_source(model, field)
            except InvalidRequest:
                stats[f"{model}.{field}"] = {"skipped": "model not available"}
        return stats

    async def _index_source(self, model: str, field: str) -> dict[str, int]:
        known = await self._store.record_hashes(model, field)
        present: list[int] = []
        pending: list[tuple[int, str, str]] = []  # (id, text to embed, hash)
        unchanged = indexed = 0
        offset = 0
        while True:
            rows = await self._odoo.call(
                model,
                "search_read",
                [[[field, "!=", False]]],
                {
                    "fields": [field, "display_name"],
                    "limit": self._page_size,
                    "offset": offset,
                    "order": "id",
                },
            )
            for row in rows:
                text = odoo_text(row.get(field))
                if not text:
                    continue
                present.append(row["id"])
                embed_text = f"{row.get('display_name') or ''}\n{text}"[:EMBED_TEXT_LIMIT]
                digest = content_hash(embed_text)
                if known.get(row["id"]) == digest:
                    unchanged += 1
                else:
                    pending.append((row["id"], embed_text, digest))
            if len(rows) < self._page_size:
                break
            offset += self._page_size

        for start in range(0, len(pending), self._batch_size):
            batch = pending[start : start + self._batch_size]
            vectors = await self._embedder.embed([text for _, text, _ in batch])
            for (record_id, _, digest), vector in zip(batch, vectors, strict=True):
                await self._store.upsert_record(
                    RecordEntry(model, record_id, field, f"{model}:{record_id}", digest, vector)
                )
                indexed += 1
        removed = await self._store.prune_records(model, field, present)
        return {"indexed": indexed, "unchanged": unchanged, "removed": removed}
