"""Text embeddings (ADR 0010): a local multilingual model behind a small interface."""

from __future__ import annotations

import math
import os
import threading
from typing import Any, Protocol

import anyio

from odoo_agent_gateway import tracing

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSION = 384  # must match the vector column in migrations/002_knowledge_index.sql


class Embedder(Protocol):
    dimension: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else list(vector)


class FastEmbedEmbedder:
    """Runs the model locally with fastembed (ONNX). Loaded on first use, in a worker thread."""

    dimension = DIMENSION

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: str | None = None) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model: Any = None
        self._lock = threading.Lock()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with tracing.span("knowledge.embed", **{"knowledge.texts": len(texts)}):
            return await anyio.to_thread.run_sync(self._embed_blocking, texts)

    def _embed_blocking(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        return [normalize([float(x) for x in vector]) for vector in model.embed(texts)]

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                # Windows without developer mode cannot create symlinks; the cache still works.
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self._model_name, cache_dir=self._cache_dir)
            return self._model
