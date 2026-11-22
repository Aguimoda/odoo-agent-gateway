from datetime import timedelta

import pytest

from odoo_agent_gateway.report import parse_since, percentile, render_markdown, summarize


def rows(tool, durations, outcome="ok"):
    return [{"tool": tool, "outcome": outcome, "duration_ms": d} for d in durations]


def test_percentiles_use_the_nearest_rank():
    values = list(range(1, 101))  # 1..100

    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 100) == 100
    assert percentile([7], 95) == 7
    assert percentile([], 95) is None


def test_each_tool_gets_calls_error_rate_errors_by_code_and_latency():
    data = (
        rows("search_records", [10, 20, 30, 40])
        + rows("search_records", [5], outcome="forbidden")
        + rows("list_models", [3, 4])
        + rows("search_records", [6], outcome="rate_limited")
    )

    report = {row["tool"]: row for row in summarize(data)}

    search = report["search_records"]
    assert search["calls"] == 6
    assert search["error_rate"] == pytest.approx(2 / 6)
    assert search["errors"] == {"forbidden": 1, "rate_limited": 1}
    assert (search["p50_ms"], search["p95_ms"], search["max_ms"]) == (10, 40, 40)
    assert report["list_models"]["error_rate"] == 0
    assert report["(all)"]["calls"] == 8


def test_tools_are_sorted_by_number_of_calls():
    data = rows("a", [1]) + rows("b", [1, 1, 1]) + rows("c", [1, 1])

    assert [row["tool"] for row in summarize(data)] == ["b", "c", "a", "(all)"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("24h", timedelta(hours=24)), ("7d", timedelta(days=7)), ("30m", timedelta(minutes=30))],
)
def test_periods_are_written_as_number_and_unit(text, expected):
    assert parse_since(text) == expected


@pytest.mark.parametrize("text", ["", "7", "d", "-1d", "1y"])
def test_bad_periods_are_refused(text):
    with pytest.raises(ValueError):
        parse_since(text)


def test_the_markdown_report_has_a_row_per_tool():
    text = render_markdown(summarize(rows("search_records", [10, 30])), "24h")

    assert "| search_records | 2 | 0% |" in text
    assert "last 24h" in text


def test_an_empty_period_says_so():
    assert "No calls" in render_markdown(summarize([]), "24h")
