# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-11-23

Milestone M4: write proposals with four-eyes approval.

### Added

- `propose_change` and `list_my_proposals` MCP tools. Proposals are checked as the proposer (allowlisted model, visible record, 1 to 10 writable fields of simple types, never state, company, archiving, line lists or binary fields, and a 10 to 500 character reason) and change nothing in Odoo.
- `/approvals` API, deliberately not an MCP tool: `GET /pending`, `POST /{id}/approve`, `POST /{id}/reject`, with the approver's own Odoo credentials (ADR 0012).
- Four-eyes rule: nobody approves their own proposal, because the agent holds its user's key. The write runs in Odoo as the approver; stale values end in `conflict`; business-rule refusals end in `failed`; missing approver rights leave the proposal pending; proposals expire after 7 days.
- `change_proposals` table storing new values and a fingerprint of the old ones (not the values), guarded by a trigger: content immutable, decisions final, no delete or truncate.
- Integration tests: Odoo records the approver as the writer, four-eyes refusal, an approver who cannot see the record, conflict, final decisions, refused fields, pending lists per approver.

### Changed

- The call path (rate limit, credentials, action, fail-closed audit) is now one `Gateway.execute`, shared by the MCP tools and the approval API.

## [0.3.0] - 2026-11-22

Milestone M3: permission-safe retrieval.

### Added

- `search_knowledge`, the seventh tool: search by meaning, in Spanish or English, over a company handbook and Odoo texts (product sale descriptions, contact notes, sales order notes), returning passages with their sources.
- Retrieval that cannot leak (ADR 0011): the pgvector index stores Odoo records only as a vector plus a reference, and the database refuses record text. The text shown is read from Odoo at query time as the asking user, so hidden records or fields never appear and answers are never stale.
- Local multilingual embeddings with `paraphrase-multilingual-MiniLM-L12-v2` through `fastembed`, behind a replaceable interface (ADR 0010). The model is warmed up at start-up.
- Offline indexer (`python -m odoo_agent_gateway.index`) run with a dedicated `indexer` account that has no admin rights. It splits Markdown by heading, re-embeds only changed records and prunes removed ones.
- Demo handbook (returns, shipping, discounts, payments), order notes including a confidential one, and the `indexer` user.
- Shared migration runner with an advisory lock (audit log and knowledge index).
- Integration tests: confidential note hidden from Ana but found by Luis, fresh text after an edit, no record text or names in the index, hostile indexed text returned as data, and a retrieval evaluation (6 of 6 in the top three). CI now builds the index, with the model cached.

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
