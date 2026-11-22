import json
from pathlib import Path

import pytest

from odoo_agent_gateway.evals.retrieval import (
    Case,
    CaseResult,
    Hit,
    calibrate,
    load_cases,
    metrics,
)

DATASET = Path(__file__).resolve().parents[2] / "evals" / "retrieval_set.json"


def answerable(case_id: str, expected: str, hits: list[tuple[str | None, float]]) -> CaseResult:
    return CaseResult(Case(case_id, "q", expected), [Hit(path, score) for path, score in hits])


def unanswerable(case_id: str, hits: list[tuple[str | None, float]]) -> CaseResult:
    return CaseResult(Case(case_id, "q", None), [Hit(path, score) for path, score in hits])


def test_the_labelled_set_loads_and_mixes_answerable_and_unanswerable_questions():
    cases = load_cases(DATASET)

    assert len(cases) >= 20
    assert len({case.id for case in cases}) == len(cases)
    assert sum(case.expected_path is None for case in cases) >= 5
    assert {json.loads(DATASET.read_text(encoding="utf-8"))["cases"][0]["lang"]} <= {"es", "en"}


def test_hits_and_reciprocal_rank_are_computed_per_question():
    results = [
        answerable("a", "returns.md", [("returns.md", 0.6), ("shipping.md", 0.4)]),  # rank 1
        answerable("b", "shipping.md", [("returns.md", 0.6), ("shipping.md", 0.5)]),  # rank 2
        answerable(
            "c",
            "payments.md",
            [("returns.md", 0.6), ("x.md", 0.5), ("y.md", 0.4), ("payments.md", 0.3)],
        ),  # rank 4
        answerable("d", "discounts.md", [("returns.md", 0.6)]),  # missed
    ]

    m = metrics(results, min_score=0.0)

    assert m["hit_at_1"] == pytest.approx(1 / 4)
    assert m["hit_at_3"] == pytest.approx(2 / 4)
    assert m["mrr"] == pytest.approx((1 + 1 / 2 + 1 / 4 + 0) / 4)


def test_a_threshold_silences_noise_for_unanswerable_questions():
    results = [
        unanswerable("x", [("returns.md", 0.31), ("payments.md", 0.29)]),
        unanswerable("y", [("shipping.md", 0.45)]),
    ]

    loose = metrics(results, min_score=0.0)
    strict = metrics(results, min_score=0.35)

    assert loose["quiet_rate"] == 0.0 and loose["mean_noise"] == 1.5
    assert strict["quiet_rate"] == 0.5 and strict["mean_noise"] == 0.5


def test_a_threshold_can_also_hide_correct_answers():
    results = [answerable("a", "returns.md", [("returns.md", 0.33)])]

    assert metrics(results, min_score=0.30)["hit_at_3"] == 1.0
    assert metrics(results, min_score=0.40)["hit_at_3"] == 0.0


def test_calibration_sweeps_thresholds_and_reports_both_sides():
    results = [
        answerable("a", "returns.md", [("returns.md", 0.55)]),
        unanswerable("x", [("returns.md", 0.30)]),
    ]

    table = calibrate(results, [0.25, 0.40, 0.60])

    assert [row["min_score"] for row in table] == [0.25, 0.40, 0.60]
    assert table[1]["hit_at_3"] == 1.0 and table[1]["quiet_rate"] == 1.0
    assert table[2]["hit_at_3"] == 0.0
