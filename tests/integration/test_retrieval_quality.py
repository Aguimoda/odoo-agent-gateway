"""Retrieval quality gate (ADR 0013): the labelled set against the real index, in CI.

The minimums leave a margin below the calibrated results (evals/results/retrieval.md), so a
real regression fails the build but a one-question wobble does not.
"""

import os
from pathlib import Path

import anyio
import httpx2
import pytest

from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.embeddings import FastEmbedEmbedder
from odoo_agent_gateway.evals.retrieval import collect, load_cases, metrics
from odoo_agent_gateway.knowledge import KnowledgeSearch
from odoo_agent_gateway.knowledge_store import PostgresKnowledgeStore
from odoo_agent_gateway.odoo import OdooClient
from odoo_agent_gateway.tools import Limits

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
MINIMUMS = {"hit_at_3": 0.85, "mrr": 0.75, "quiet_rate": 0.80}


def missing(reason: str):
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def results():
    keys = ROOT / ".env.demo-keys"
    if not keys.exists():
        missing("Demo data missing: run scripts/demo/setup_demo.py first.")
    env = dict(
        line.split("=", 1)
        for line in keys.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )

    async def run():
        store = PostgresKnowledgeStore(env["GATEWAY_DATABASE_URL"])
        embedder = FastEmbedEmbedder(
            cache_dir=os.environ.get("GATEWAY_MODEL_CACHE", ".cache/models")
        )
        knowledge = KnowledgeSearch(store, embedder, Limits(), min_score=0.0)
        await store.start()
        try:
            async with httpx2.AsyncClient(timeout=60) as http:
                client = OdooClient(env["ODOO_URL"], env["ODOO_DB"], http)
                session = await client.authenticate(env["DEMO_ANA_LOGIN"], env["DEMO_ANA_API_KEY"])
                return await collect(
                    lambda question, limit: knowledge.search(session, question, limit),
                    load_cases(ROOT / "evals" / "retrieval_set.json"),
                )
        finally:
            await store.close()

    return anyio.run(run)


def test_retrieval_meets_the_agreed_minimums_at_the_calibrated_threshold(results):
    threshold = Settings(odoo_url="x", odoo_db="x").knowledge_min_score

    measured = metrics(results, threshold)

    for name, minimum in MINIMUMS.items():
        assert measured[name] >= minimum, f"{name} {measured[name]:.2f} < {minimum} at {threshold}"


def test_the_threshold_removes_noise_without_losing_answers(results):
    threshold = Settings(odoo_url="x", odoo_db="x").knowledge_min_score

    without, with_threshold = metrics(results, 0.0), metrics(results, threshold)

    assert with_threshold["mean_noise"] < without["mean_noise"]
    assert with_threshold["hit_at_3"] == without["hit_at_3"]
