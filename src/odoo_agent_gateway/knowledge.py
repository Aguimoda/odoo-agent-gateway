"""search_knowledge: retrieval that cannot show what Odoo would not show (ADR 0011).

The index only ranks. For records, every text shown comes from Odoo at query time, read as
the asking user; anything Odoo hides, or any field it refuses, is dropped.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from odoo_agent_gateway.embeddings import Embedder
from odoo_agent_gateway.knowledge_store import Candidate, KnowledgeStore
from odoo_agent_gateway.odoo import AccessDenied, InvalidRequest, RecordNotFound
from odoo_agent_gateway.textutil import odoo_text
from odoo_agent_gateway.tools import NOTICE, Limits, Session

MAX_QUERY_LENGTH = 500
MAX_RESULTS = 10
DEFAULT_RESULTS = 5
CANDIDATES = 100
# Minimum cosine similarity for a passage to be returned. Calibrated in M5 with the retrieval
# evaluation (evals/results/retrieval.md): from 0.41 to 0.43 no answerable question is lost and
# every unanswerable one returns nothing; 0.42 is the middle. Override: GATEWAY_KNOWLEDGE_MIN_SCORE.
DEFAULT_MIN_SCORE = 0.42


class KnowledgeSearch:
    def __init__(
        self,
        store: KnowledgeStore,
        embedder: Embedder,
        limits: Limits,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> None:
        self._min_score = min_score
        self._store = store
        self._embedder = embedder
        self._limits = limits

    async def search(self, session: Session, query: Any, limit: Any = None) -> dict[str, Any]:
        query = self._check_query(query)
        limit = self._check_limit(limit)
        (vector,) = await self._embedder.embed([query])
        candidates = [
            candidate
            for candidate in await self._store.search(vector, CANDIDATES)
            if candidate.score >= self._min_score
        ]
        visible_texts = await self._visible_record_texts(session, candidates)

        results: list[dict[str, Any]] = []
        truncated = False
        for candidate in candidates:
            if len(results) >= limit:
                break
            if candidate.kind == "document":
                text, title = candidate.content or "", candidate.title
                source = {"path": candidate.doc_path, "section": candidate.chunk_index}
            else:
                key = (candidate.model, candidate.field, candidate.record_id)
                if key not in visible_texts:
                    continue
                text, title = visible_texts[key]
                source = {
                    "model": candidate.model,
                    "id": candidate.record_id,
                    "field": candidate.field,
                }
            if not text:
                continue
            if len(text) > self._limits.max_text:
                text = text[: self._limits.max_text] + " [truncated]"
                truncated = True
            results.append(
                {
                    "type": candidate.kind,
                    "title": title,
                    "source": source,
                    "text": text,
                    "score": round(candidate.score, 3),
                }
            )
        return {
            "query": query,
            "results": results,
            "returned": len(results),
            "truncated": truncated,
            "notice": NOTICE,
        }

    async def _visible_record_texts(
        self, session: Session, candidates: list[Candidate]
    ) -> dict[tuple[str, str, int], tuple[str, str]]:
        """Ask Odoo, as the user, which candidate records are visible and what they say now."""
        groups: dict[tuple[str, str], list[int]] = defaultdict(list)
        for candidate in candidates:
            if candidate.kind == "record" and candidate.model in self._limits.allowed_models:
                ids = groups[(candidate.model, candidate.field)]
                if candidate.record_id not in ids:
                    ids.append(candidate.record_id)

        texts: dict[tuple[str, str, int], tuple[str, str]] = {}
        for (model, field), ids in groups.items():
            try:
                visible = await session.call(model, "search", [[["id", "in", ids]]])
                if not visible:
                    continue
                rows = await session.call(model, "read", [visible, [field, "display_name"]])
            except (AccessDenied, RecordNotFound, InvalidRequest):
                continue  # the user may not read this model or field: show nothing from it
            for row in rows:
                texts[(model, field, row["id"])] = (
                    odoo_text(row.get(field)),
                    str(row.get("display_name") or ""),
                )
        return texts

    @staticmethod
    def _check_query(query: Any) -> str:
        if not isinstance(query, str) or not query.strip():
            raise InvalidRequest("query must be a non-empty question or phrase.")
        if len(query) > MAX_QUERY_LENGTH:
            raise InvalidRequest(f"query must be at most {MAX_QUERY_LENGTH} characters.")
        return query.strip()

    @staticmethod
    def _check_limit(limit: Any) -> int:
        if limit is None:
            return DEFAULT_RESULTS
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RESULTS:
            raise InvalidRequest(f"limit must be between 1 and {MAX_RESULTS}.")
        return limit
