"""Retrieval evaluation (ADR 0013): how well search_knowledge ranks, and when it stays quiet.

Scores are collected once with no threshold; metrics are then computed for any threshold,
so calibrating the relevance threshold needs no extra queries.

    python -m odoo_agent_gateway.evals.retrieval --calibrate

Environment: ODOO_URL, ODOO_DB, GATEWAY_DATABASE_URL, DEMO_ANA_LOGIN, DEMO_ANA_API_KEY,
optional GATEWAY_MODEL_CACHE. Writes evals/results/retrieval.json and retrieval.md.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TOP_K = 5
SWEEP = [round(0.20 + 0.01 * step, 2) for step in range(41)]  # 0.20 .. 0.60


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    expected_path: str | None  # None: the handbook cannot answer it


@dataclass(frozen=True)
class Hit:
    path: str | None  # None for Odoo records
    score: float


@dataclass
class CaseResult:
    case: Case
    hits: list[Hit] = field(default_factory=list)


def load_cases(path: Path) -> list[Case]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Case(c["id"], c["question"], c["expected_path"]) for c in data["cases"]]


async def collect(
    search: Callable[[str, int], Awaitable[dict[str, Any]]], cases: list[Case]
) -> list[CaseResult]:
    """Run every question once, with no threshold, keeping the top TOP_K results."""
    results = []
    for case in cases:
        answer = await search(case.question, TOP_K)
        hits = [Hit(hit["source"].get("path"), float(hit["score"])) for hit in answer["results"]]
        results.append(CaseResult(case, hits))
    return results


def _rank(result: CaseResult, min_score: float) -> int | None:
    kept = [hit for hit in result.hits if hit.score >= min_score][:TOP_K]
    for position, hit in enumerate(kept, start=1):
        if hit.path == result.case.expected_path:
            return position
    return None


def metrics(results: list[CaseResult], min_score: float) -> dict[str, float]:
    answerable = [r for r in results if r.case.expected_path is not None]
    unanswerable = [r for r in results if r.case.expected_path is None]
    ranks = [_rank(r, min_score) for r in answerable]
    noise = [len([hit for hit in r.hits if hit.score >= min_score][:TOP_K]) for r in unanswerable]
    count = max(len(answerable), 1)
    return {
        "min_score": min_score,
        "hit_at_1": sum(rank == 1 for rank in ranks) / count,
        "hit_at_3": sum(rank is not None and rank <= 3 for rank in ranks) / count,
        "mrr": sum(1 / rank for rank in ranks if rank) / count,
        "quiet_rate": sum(n == 0 for n in noise) / max(len(unanswerable), 1),
        "mean_noise": sum(noise) / max(len(unanswerable), 1),
    }


def calibrate(results: list[CaseResult], thresholds: list[float]) -> list[dict[str, float]]:
    return [metrics(results, threshold) for threshold in thresholds]


def _round(values: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 4) for key, value in values.items()}


def report_markdown(summary: dict[str, Any]) -> str:
    m = summary["metrics"]
    lines = [
        "# Retrieval evaluation",
        "",
        f"Model `{summary['model']}`, {summary['cases']} questions "
        f"({summary['answerable']} answerable, {summary['unanswerable']} unanswerable), "
        f"threshold {m['min_score']}, run {summary['run_at']}.",
        "",
        "| hit@1 | hit@3 | MRR | quiet on unanswerable | mean noise |",
        "|---|---|---|---|---|",
        f"| {m['hit_at_1']:.2f} | {m['hit_at_3']:.2f} | {m['mrr']:.2f} | "
        f"{m['quiet_rate']:.2f} | {m['mean_noise']:.2f} |",
    ]
    if summary.get("calibration"):
        lines += [
            "",
            "## Threshold sweep",
            "",
            "| threshold | hit@3 | MRR | quiet | noise |",
            "|---|---|---|---|---|",
        ]
        for row in summary["calibration"]:
            lines.append(
                f"| {row['min_score']:.2f} | {row['hit_at_3']:.2f} | {row['mrr']:.2f} | "
                f"{row['quiet_rate']:.2f} | {row['mean_noise']:.2f} |"
            )
    lines += [
        "",
        "## Per question",
        "",
        "| id | expected | rank | top score |",
        "|---|---|---|---|",
    ]
    for case in summary["per_case"]:
        lines.append(
            f"| {case['id']} | {case['expected'] or '(none)'} | {case['rank'] or '-'} | "
            f"{case['top_score']:.3f} |"
        )
    return "\n".join(lines) + "\n"


def summarize(
    results: list[CaseResult], min_score: float, model: str, sweep: bool
) -> dict[str, Any]:
    return {
        "model": model,
        "run_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        "cases": len(results),
        "answerable": sum(r.case.expected_path is not None for r in results),
        "unanswerable": sum(r.case.expected_path is None for r in results),
        "metrics": _round(metrics(results, min_score)),
        "calibration": [_round(row) for row in calibrate(results, SWEEP)] if sweep else [],
        "per_case": [
            {
                "id": r.case.id,
                "expected": r.case.expected_path,
                "rank": _rank(r, min_score),
                "top_score": round(r.hits[0].score, 4) if r.hits else 0.0,
            }
            for r in results
        ],
    }


async def _run(dataset: Path, out: Path, min_score: float, sweep: bool) -> dict[str, Any]:
    import httpx2

    from odoo_agent_gateway.embeddings import DEFAULT_MODEL, FastEmbedEmbedder
    from odoo_agent_gateway.knowledge import KnowledgeSearch
    from odoo_agent_gateway.knowledge_store import PostgresKnowledgeStore
    from odoo_agent_gateway.odoo import OdooClient
    from odoo_agent_gateway.tools import Limits

    env = os.environ
    store = PostgresKnowledgeStore(env["GATEWAY_DATABASE_URL"])
    embedder = FastEmbedEmbedder(cache_dir=env.get("GATEWAY_MODEL_CACHE", ".cache/models"))
    knowledge = KnowledgeSearch(store, embedder, Limits(), min_score=0.0)
    await store.start()
    try:
        async with httpx2.AsyncClient(timeout=60) as http:
            client = OdooClient(env["ODOO_URL"], env["ODOO_DB"], http)
            session = await client.authenticate(env["DEMO_ANA_LOGIN"], env["DEMO_ANA_API_KEY"])
            results = await collect(
                lambda question, limit: knowledge.search(session, question, limit),
                load_cases(dataset),
            )
    finally:
        await store.close()
    summary = summarize(results, min_score, DEFAULT_MODEL, sweep)
    out.mkdir(parents=True, exist_ok=True)
    (out / "retrieval.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "retrieval.md").write_text(report_markdown(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> None:
    import anyio

    from odoo_agent_gateway.knowledge import DEFAULT_MIN_SCORE

    parser = argparse.ArgumentParser(description="Evaluate search_knowledge retrieval.")
    parser.add_argument("--dataset", type=Path, default=Path("evals/retrieval_set.json"))
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--calibrate", action="store_true", help="also sweep thresholds")
    args = parser.parse_args(argv)
    summary = anyio.run(_run, args.dataset, args.out, args.min_score, args.calibrate)
    print(json.dumps(summary["metrics"], indent=2))


if __name__ == "__main__":
    main()
