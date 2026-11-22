# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-22

Milestone M2: audit, rate limits and the leak suite in CI.

### Added

- Append-only audit log in the gateway's PostgreSQL: one row per tool call, including failed logins, guardrail errors and rate-limited calls. No credentials or returned data are stored; triggers reject `UPDATE`, `DELETE` and `TRUNCATE` (ADR 0008).
- Fail-closed behaviour: a call whose audit row cannot be written returns `audit_unavailable` and no data. The gateway does not start without `GATEWAY_DATABASE_URL`.
- Per-login sliding-window rate limit, checked before contacting Odoo (`GATEWAY_RATE_LIMIT_PER_MINUTE`, default 60; ADR 0009).
- Hostile demo records: a note that tries to steer the agent and an oversized note.
- Integration tests for filtering by another user's order ids, reading another user's order lines, hostile records, audit rows and the absence of keys in the audit log (21 integration tests in total).
- CI job that runs the integration suite against a real Odoo 18 in Docker on every push, failing rather than skipping if the demo setup is missing.

## [0.1.0] - 2026-11-22

Milestone M1: read-only MCP server.

### Added

- Six read tools over MCP: `my_permissions`, `list_models`, `describe_model`, `search_records`, `read_record`, `summarize_data`.
- Every call runs as the caller: the gateway authenticates the `X-Odoo-Login` and `Authorization: Bearer <API key>` headers against Odoo on each request and stores no credentials (ADR 0005).
- Guardrails on the read tools: model allowlist, plain field names only, fixed operators and aggregates, size limits, text truncation, and a notice that returned values are data (ADR 0006).
- MCP over stateless streamable HTTP at `/mcp`, next to `/health`, with Host and Origin checks on (ADR 0007).
- Async JSON-RPC client for Odoo 18 with error mapping that never forwards access-error details or credentials.
- `python -m odoo_agent_gateway` to run the server.
- Reproducible demo data (`scripts/demo/setup_demo.py`) with two users of different sales rights.
- Unit tests (67) and integration tests (9) against the demo database.

### Changed

- HTTP client is now `httpx2`, the one the official MCP SDK uses; `httpx` is no longer needed.

## [0.0.1] - 2026-11-22

Milestone M0: foundations.

### Added

- Specification, tool catalogue and architecture decision records (ADR 0001 to 0004).
- Python project with FastAPI, an application factory and a `GET /health` endpoint, written test-first.
- Docker Compose stack: Odoo 18, its PostgreSQL, and a separate PostgreSQL with pgvector for the gateway.
- GitHub Actions workflow: lint and tests on Python 3.11 and 3.12, Compose validation, secret scan.
