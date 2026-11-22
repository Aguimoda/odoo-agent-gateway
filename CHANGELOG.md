# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
