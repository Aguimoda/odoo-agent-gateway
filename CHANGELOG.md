# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.8.0] - 2026-11-23

Milestone M8: the assistant inside Odoo (ADR 0021).

### Added

- Odoo 18 module `agent_gateway_connector` (`odoo_addon/`): a top-bar button with a side panel, an Assistant menu (chat, approvals inbox, administration for Settings administrators), Settings → AI assistant, and "Revoke assistant access" in each person's Preferences.
- Consent before anything: the module creates, as the person and never with sudo, an Odoo API key limited to RPC that expires after 8 hours, and hands it to the gateway server to server. At most five per person; failures leave none.
- `POST /session/ticket` and `POST /session/redeem`: a one-time ticket (60 seconds, stored as a hash, single use, in the URL fragment) that the panel exchanges for the usual cookie; a ticket never works as a cookie. Migration 008.
- `GATEWAY_EMBED_ORIGINS`: the Odoo origins allowed to show the app in a panel (`frame-ancestors`); by default nobody.
- The web app's compact mode under `/app/embed`, which asks the Odoo page for a ticket when it has no session and closes a session that belongs to someone else.
- The module's ten tests run inside Odoo in CI, and browser tests sign in to Odoo, allow the assistant, chat, revoke, and open the inbox from Odoo's menu.
- Demo: the module installed and configured, and browser passwords for Ana, Luis and Carmen.

### Fixed

- Adding a model to a provider without a default made it the default for the whole gateway, silently replacing another provider's default.

## [0.7.1] - 2026-11-23

Milestone M7.1: what the first tests with real free providers (Groq, Gemini, OpenRouter, NVIDIA, Cloudflare) showed, fixed and measured (ADR 0020).

### Added

- Model catalog: `GET /admin/providers/{id}/catalog` and "Browse models" in the admin panel list every model a provider offers with its context size, whether it takes tools and its kind, models that take tools first, and add one with a click. Cloudflare Workers AI, which has no `/models`, is read from its model search API.
- Provider templates for Gemini, OpenRouter, NVIDIA NIM, Cloudflare Workers AI (from the account id), Mistral and LM Studio, next to Groq, Cerebras, OpenAI and Ollama. Each says what kind of plan it had when checked and links the provider's limits page.
- Tokens-per-minute budget per provider, checked before each call against the tokens of the last minute: short waits are absorbed, longer ones answer `rate_limited` with the wait without calling the provider. Token counts are requested in streams, and estimated when a provider does not report them.
- The provider's short error code of each failed call is kept in `llm_usage.error_code`, and the reason a provider refused a request goes to the server log (never the key).

### Fixed

- When the agent ran out of steps the person could get nothing: the last call now carries the tool results as plain text with no tools offered, and an empty or tool-markup reply becomes an honest "could not finish" message in the person's language.
- An error event inside a stream is classified from its content instead of always meaning "provider down".
- Gemini: the `thought_signature` of each tool call is sent back, which Gemini requires.
- Cloudflare: an assistant turn that only calls tools sends empty text instead of `null`, and number pieces in a stream no longer break the answer.
- Signing out and signing in as someone else on the same tab no longer lands on the previous person's conversation.

## [0.7.0] - 2026-11-23

Milestone M7: the web app. People sign in once and use the assistant, the approvals inbox and the admin panel from a browser.

### Added

- Web app at `/app`, built from `web/` with React 19, TypeScript and Vite and served by the gateway from the same origin (ADR 0019): chat with streamed Markdown answers and the trail of tools used as the person, proposals, notices, provider failures with a countdown and the other models as buttons; approvals inbox with current against proposed values; admin panel for providers, models, connection tests, agent settings and usage. Spanish and English, light and dark, keyboard shortcuts, accessible, works on a phone.
- Web sessions (ADR 0018): `POST`/`GET`/`DELETE /session`. The Odoo key is checked by Odoo, kept encrypted on the server and bound to the session id; the browser only holds an `HttpOnly`, `SameSite=Strict` cookie. Cookie requests that change something must come from the gateway's own origin, `/mcp` never accepts the cookie, and sessions expire after 2 hours idle or 12 hours.
- Strict Content Security Policy and security headers on the app; no inline scripts or styles, no third-party requests.
- `GET /approvals/mine`: your own proposals and what happened to them.
- The admin settings list the real tool names, for disabling tools from the panel.
- A conversation started without a title takes it from its first message; empty conversations are not listed.
- `scripts/demo/fake_llm.py`: a scripted OpenAI-compatible model for demos and browser tests.
- Browser tests with Playwright against real Odoo (`pip install -e ".[e2e]"`), and a CI job that type-checks, lints, tests and builds the web app.

### Fixed

- The approvals inbox read the 200 oldest pending proposals of any kind and filtered them afterwards, so proposals on other models (or by the approver) could crowd out newer ones that should have been shown. The filter now runs in SQL before the limit.

## [0.6.0] - 2026-11-23

Milestone M6: the agent service and its providers. The roadmap now follows the product plan (`docs/PRODUCT-PLAN.md`): M7 web chat and admin panel, M8 Odoo module, M9 deployment.

### Added

- `/agent` API: conversations and answers streamed as Server-Sent Events (`start`, `token`, `tool_call`, `tool_result`, `proposal`, `notice`, `error`, `done`). The agent's tool calls go through the gateway's own MCP endpoint in process with the person's key, so they are rate-limited, permission-checked and audited like any agent's (ADR 0016).
- Safe default instructions that carry the lessons of the real-agent evaluation (say plainly when something was not found; never claim a change that was only proposed), and a final answer without tools when the step limit is reached. Company instructions only add to them.
- Private conversations, owned by the Odoo user id and filtered by it in SQL, deletable by their owner and purged after a configurable retention. Tool names and arguments are kept; what the tools returned is not.
- Provider registry for any OpenAI-compatible API. Keys are encrypted with AES-256-GCM under master keys from `GATEWAY_SECRET_KEYS`, bound to the provider URL, write-only, and replaced by `***` in the audit log; plain `http` only reaches local hosts and redirects are never followed (ADR 0015).
- `/admin` API for providers, models, connection tests, agent settings and usage, answering only to members of `GATEWAY_ADMIN_GROUP` as Odoo reports it.
- Provider failures classified into seven kinds and explained with the other models available; no automatic fallback, and `/retry` with the model the person picks. Short waits absorbed, refused keys and used-up quotas tracked, a per-provider circuit breaker, and optional per-minute and per-day limits (ADR 0017).
- Usage per call (provider, model, person, outcome, tokens, latency) and its summary.
- Demo: Carmen, an IT administrator without sales rights, a master key kept across runs, and `scripts/demo/try_assistant.py` to talk to the assistant with a real provider.

### Changed

- The approval, admin and agent APIs share one helper for the host check, the Gateway path and error responses.

## [0.5.0] - 2026-11-23

Milestone M5: evaluation and observability.

### Added

- Retrieval evaluation: 24 labelled questions in Spanish and English, 6 unanswerable, with hit@1, hit@3, MRR, quiet rate and noise computed for any threshold from one collection run (`python -m odoo_agent_gateway.evals.retrieval --calibrate`). Results committed under `evals/results/`.
- A relevance threshold calibrated from that data: 0.42 keeps every answer found without a threshold (hit@3 0.94, MRR 0.88) and silences all unanswerable questions, which previously returned five passages each. CI gates hit@3, MRR and quiet rate.
- OpenTelemetry spans for each call, Odoo RPC, embedding, index search and audit write, off by default (`GATEWAY_TRACES=console|otlp`, OTLP as an optional extra); the audit log stores the trace id (migration 004). Spans never carry keys or argument values.
- Usage report from the audit log (`python -m odoo_agent_gateway.report`): calls, error codes and p50/p95/max latency per tool.
- Real-agent evaluation for any OpenAI-compatible provider (Groq, Cerebras or local), with ten scenarios scoring tool choice, citations, cross-user leaks and hostile-text resistance. The provider key is read from the environment only.

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
