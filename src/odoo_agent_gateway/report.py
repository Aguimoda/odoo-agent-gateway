"""Usage report from the audit log: calls, errors and latency per tool.

    python -m odoo_agent_gateway.report --since 24h [--format md|json]

Reads GATEWAY_DATABASE_URL. Only reads: the audit log is append-only (ADR 0008).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

_PERIOD = re.compile(r"^(\d+)([mhd])$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


def parse_since(text: str) -> timedelta:
    match = _PERIOD.match((text or "").strip())
    if not match or int(match.group(1)) == 0:
        raise ValueError("--since must look like 30m, 24h or 7d.")
    return timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})


def percentile(values: list[int], p: float) -> int | None:
    """Nearest-rank percentile: the smallest value with at least p% of values at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(p / 100 * len(ordered)) - 1, 0)]


def _row(tool: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [item["duration_ms"] for item in items]
    errors = Counter(item["outcome"] for item in items if item["outcome"] != "ok")
    return {
        "tool": tool,
        "calls": len(items),
        "error_rate": sum(errors.values()) / len(items) if items else 0,
        "errors": dict(sorted(errors.items())),
        "p50_ms": percentile(durations, 50),
        "p95_ms": percentile(durations, 95),
        "max_ms": max(durations) if durations else None,
    }


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_tool[row["tool"]].append(row)
    tools = sorted(by_tool, key=lambda tool: (-len(by_tool[tool]), tool))
    return [_row(tool, by_tool[tool]) for tool in tools] + [_row("(all)", rows)]


def render_markdown(summary: list[dict[str, Any]], since: str) -> str:
    if summary[-1]["calls"] == 0:
        return f"# Gateway usage, last {since}\n\nNo calls in this period.\n"
    lines = [
        f"# Gateway usage, last {since}",
        "",
        "| tool | calls | errors | p50 ms | p95 ms | max ms | error codes |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summary:
        codes = ", ".join(f"{code} {count}" for code, count in row["errors"].items()) or "-"
        lines.append(
            f"| {row['tool']} | {row['calls']} | {row['error_rate']:.0%} | {row['p50_ms']} | "
            f"{row['p95_ms']} | {row['max_ms']} | {codes} |"
        )
    return "\n".join(lines) + "\n"


async def fetch(dsn: str, since: timedelta) -> list[dict[str, Any]]:
    import asyncpg

    connection = await asyncpg.connect(dsn)
    try:
        rows = await connection.fetch(
            """
            select tool, outcome, duration_ms from audit_log
            where occurred_at >= now() - $1::interval
            """,
            since,
        )
    finally:
        await connection.close()
    return [dict(row) for row in rows]


def main(argv: list[str] | None = None) -> None:
    import anyio

    parser = argparse.ArgumentParser(description="Usage report from the audit log.")
    parser.add_argument("--since", default="24h", help="period such as 30m, 24h or 7d")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    args = parser.parse_args(argv)
    dsn = os.environ.get("GATEWAY_DATABASE_URL")
    if not dsn:
        raise SystemExit("GATEWAY_DATABASE_URL is required.")
    summary = summarize(anyio.run(fetch, dsn, parse_since(args.since)))
    if args.format == "json":
        print(json.dumps(summary, indent=2))
    else:
        print(render_markdown(summary, args.since), end="")


if __name__ == "__main__":
    main()
