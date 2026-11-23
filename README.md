# Odoo Agent Gateway

[![CI](https://github.com/Aguimoda/odoo-agent-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/Aguimoda/odoo-agent-gateway/actions/workflows/ci.yml)

A permission-aware [MCP](https://modelcontextprotocol.io) gateway that lets AI agents work on Odoo **as the person asking, never as an administrator**.

> **Status: milestone M7 done (version 0.7.0).** Nine MCP tools: seven to read (including permission-safe retrieval) and two to propose changes that a different person approves through a separate API. Each call runs with the caller's own Odoo API key, is audited, rate-limited and traced. Since M6 the gateway also runs the assistant itself: streamed answers, providers configured by Odoo administrators with encrypted keys, and provider failures explained instead of hidden. Since M7 people use it from a web app: chat, approvals inbox and admin panel, with the Odoo key kept on the server. Retrieval quality is measured against a labelled set and gated in CI, and the whole acceptance suite runs against a real Odoo 18 on every push. Not production-ready yet: the Odoo module comes in M8 and the public deployment in M9.

## The problem

Every company that runs Odoo wants an AI assistant that can answer "which invoices are overdue for this customer?". The easy way to build it is to hand the agent a powerful account. Then anyone using the assistant can read what Odoo would refuse them, and a manipulated agent can change data with nobody accountable.

## How the gateway works

```
MCP client (an agent)
   │  MCP over HTTP, with the user's token
┌──▼────────────────────────────────┐
│ Gateway (FastAPI)                 │
│  - user token → that user's Odoo  │
│    API key (no admin account)     │
│  - read tools, proposal-only      │
│    write tools                    │
│  - audit log, rate limits         │
└──┬───────────────┬────────────────┘
   │ JSON-RPC      │ SQL
┌──▼─────────┐ ┌───▼───────────────┐
│ Odoo 18    │ │ PostgreSQL +      │
│ Community  │ │ pgvector (own DB) │
└────────────┘ └───────────────────┘
```

- **Acts as the user.** Requests reach Odoo with the asking user's API key, so Odoo's own access rights and record rules decide what is visible ([ADR 0002](docs/adr/0002-act-as-the-user-no-sudo.md)).
- **Proposes, never executes.** The agent can only propose a change. A **different** person approves it through a separate API, and the change runs in Odoo **with the approver's rights**, so Odoo checks them at that moment. Nobody approves their own proposal, because the agent holds its user's key; edits made in between end in a conflict instead of being overwritten ([ADR 0003](docs/adr/0003-agent-proposes-human-approves.md), [ADR 0012](docs/adr/0012-four-eyes-approval.md)).
- **Retrieval that cannot leak.** The vector index only ranks. Odoo record texts are never stored in it; the text shown is read from Odoo at query time, as the asking user, so a hidden record or field never appears ([ADR 0011](docs/adr/0011-index-ranks-odoo-answers.md)). Embeddings run locally, so no company text goes to a third party ([ADR 0010](docs/adr/0010-local-multilingual-embeddings.md)).
- **Accountable.** Every call, including failed logins and refused ones, leaves a row in an append-only audit log; if the row cannot be written, no data is returned ([ADR 0008](docs/adr/0008-append-only-audit-log.md)).
- **Provable.** Permission-leak checks run in CI against a real Odoo 18 with two demo users of different rights and hostile demo records.

## Version 1 tools

| Tool | Purpose | Milestone |
|---|---|---|
| `my_permissions` | What the asking user may see and do | M1 |
| `list_models` | Accessible data areas | M1 |
| `describe_model` | Fields of a data area | M1 |
| `search_records` | Filtered search | M1 |
| `read_record` | One record | M1 |
| `summarize_data` | Counts and sums, grouped | M1 |
| `search_knowledge` | Search by meaning over the handbook and the Odoo texts the caller may see, with sources | M3 |
| `propose_change` | Propose a change to one record; nothing changes until a different person approves | M4 |
| `list_my_proposals` | Status of the user's proposals | M4 |

Deliberately not offered: deleting records, free-form SQL, calling arbitrary Odoo methods, privileged accounts, and changes without human approval. Details in [docs/TOOLS.md](docs/TOOLS.md) (Spanish).

## Roadmap

| Milestone | Delivers | Status |
|---|---|---|
| M0 | Repository, specification, decisions, local stack, CI | Done |
| M1 | Read-only MCP server using each user's Odoo API key, test-first | Done |
| M2 | Audit log, rate limits, permission-leak suite in CI against real Odoo | Done |
| M3 | Retrieval with pgvector, filtered by permissions | Done |
| M4 | Write proposals with four-eyes approval | Done |
| M5 | Retrieval evaluation in CI, calibrated threshold, traces, usage report, real-agent harness | Done |
| M6 | Agent service: streamed answers, providers with encrypted keys, explained provider failures, usage | Done |
| M7 | Web chat, admin panel and approval inbox | Done |
| M8 | Odoo module: the chat and the inbox inside Odoo | Planned |
| M9 | Cloud deployment with a public demo, and a short video | Planned |

The full plan, threat model and evaluation design are in [docs/SPEC.md](docs/SPEC.md) (Spanish).

## Run it locally

Requirements: Docker with Compose, Python 3.11 or newer, and Node.js 22.12 or newer for the web app.

```bash
cp .env.example .env               # then replace every placeholder password
docker compose up -d               # Odoo 18 on http://127.0.0.1:8069 plus two PostgreSQL databases

python -m venv .venv
.venv/bin/pip install -e ".[dev]"  # on Windows: .venv\Scripts\pip

python scripts/demo/setup_demo.py  # demo database with users "ana", "luis", "carmen" and "indexer"

set -a; . ./.env.demo-keys; set +a  # load the demo settings into the shell
.venv/bin/python -m odoo_agent_gateway.index --docs scripts/demo/knowledge   # build the knowledge index
```

`setup_demo.py` creates a `demo` database with the Sales app and two users: **Ana** (sales, sees only her own orders) and **Luis** (sales administrator, sees everything). It also adds an `indexer` service account (reads all sales documents, no admin rights), notes on orders including a confidential one on Luis's order, and two hostile records used by the tests. API keys, order ids, a random password for the demo administrator and the gateway database URL are written to `.env.demo-keys`, which git ignores. Odoo's default admin password is not kept.

The index command runs separately from the gateway with the `indexer` account (ADR 0011). It indexes the demo handbook in `scripts/demo/knowledge/` and three Odoo texts: product sale descriptions, contact notes and sales order notes. Only changed records are re-embedded. The first run downloads the embedding model (about 220 MB) into `.cache/models`.

### Start the gateway

```bash
.venv/bin/python -m odoo_agent_gateway   # MCP endpoint on http://127.0.0.1:8000/mcp
```

`GATEWAY_DATABASE_URL` is required: the gateway does not start without its audit log. It applies its database migrations (audit log and knowledge index) on start-up and loads the embedding model before accepting calls.

An MCP client connects to `http://127.0.0.1:8000/mcp` with two headers per request (ADR 0005):

```
X-Odoo-Login: ana
Authorization: Bearer <Ana's Odoo API key>
```

The gateway stores no credentials; Odoo checks them on every call.

Optional settings: `GATEWAY_COOKIE_SECURE` (force the `Secure` cookie flag behind a TLS proxy), `GATEWAY_WEB_DIR` (another build of the web app), `GATEWAY_RATE_LIMIT_PER_MINUTE` (default 60 per login), `GATEWAY_MODEL_CACHE` (default `.cache/models`), `GATEWAY_KNOWLEDGE_MIN_SCORE` (default 0.42, calibrated), `GATEWAY_TRACES` (`none`, `console` or `otlp`), `GATEWAY_ALLOWED_MODELS` (comma-separated, default contacts, products and sales), `GATEWAY_ALLOWED_HOSTS` and `GATEWAY_ALLOWED_ORIGINS` (default local only), `GATEWAY_HOST` and `GATEWAY_PORT`.

### Audit log

Each tool call writes one row to `audit_log`: time, request id, the login the caller claimed, the Odoo user id when Odoo confirmed it, tool, arguments, outcome (`ok` or an error code such as `unauthenticated`, `forbidden` or `rate_limited`), number of records returned and duration. API keys and returned data are never stored, and the table rejects `UPDATE`, `DELETE` and `TRUNCATE`.

### Approving proposals

Approval is not an MCP tool. A different person uses the approval API with their own Odoo login and API key, the same two headers as MCP:

```bash
# proposals by others on records you can read, with live values
curl -H "X-Odoo-Login: luis" -H "Authorization: Bearer $LUIS_KEY" \
     http://127.0.0.1:8000/approvals/pending

# approve (or /reject) with a note
curl -X POST -H "X-Odoo-Login: luis" -H "Authorization: Bearer $LUIS_KEY" \
     -H "Content-Type: application/json" -d '{"note": "Checked with the customer."}' \
     http://127.0.0.1:8000/approvals/42/approve
```

Possible outcomes: `applied`, `conflict` (the record changed after the proposal), `failed` (Odoo refused the values), `expired` (older than 7 days) or `rejected`. Errors: `four_eyes` (your own proposal), `forbidden` (you cannot see or edit the record; it stays pending for someone who can), `conflict` (already decided). Every decision is audited.

### The assistant

The gateway also runs the agent itself ([ADR 0016](docs/adr/0016-agent-service-through-the-mcp-endpoint.md)): a person sends a message and the answer streams back while it is written, with the agent using the tools **as that person**. Its tool calls go through the gateway's own `/mcp` endpoint in process, so they are rate-limited, permission-checked and audited exactly like an external agent's. The web app below is built on this API.

It is on when `GATEWAY_SECRET_KEYS` is set. `setup_demo.py` writes one to `.env.demo-keys` and keeps it across runs; for a server, generate one with `python -m odoo_agent_gateway.secretbox`.

**Try it with a real provider** (Groq or Cerebras free tiers work). With the gateway running:

```bash
.venv/bin/python scripts/demo/try_assistant.py --provider groq                 # asks as Ana
.venv/bin/python scripts/demo/try_assistant.py --provider groq --user luis "¿Qué pedidos tiene Acme Demo SL?"
```

The first time, the demo IT administrator registers the provider and you type its API key at a prompt that does not echo. Tool calls show in brackets, and a provider failure lists the models you could switch to.

**Administration** ([ADR 0015](docs/adr/0015-encrypted-provider-keys-and-odoo-admin-group.md)). Odoo decides who administers: members of `GATEWAY_ADMIN_GROUP` (default `base.group_system`, Settings), asked of Odoo as the caller. In the demo that is **Carmen** (IT, no sales rights); Ana and Luis get `forbidden`.

```bash
# add a provider; the key is encrypted, bound to this URL, and never shown again
curl -X POST -H "X-Odoo-Login: carmen" -H "Authorization: Bearer $CARMEN_KEY" \
     -H "Content-Type: application/json" \
     -d '{"name": "groq", "base_url": "https://api.groq.com/openai/v1", "api_key": "..."}' \
     http://127.0.0.1:8000/admin/providers
```

| Endpoint | What it does |
|---|---|
| `GET /admin/providers` | Providers, their models and health (`ok`, `auth_failed`, `exhausted` until when, `circuit_open`…). Keys are never returned |
| `POST /admin/providers`, `PATCH`/`DELETE /admin/providers/{id}` | Add, change or remove a provider. Changing its URL requires the key again; plain `http` only for local hosts |
| `POST /admin/providers/{id}/test` | Checks URL and key by listing the provider's models |
| `POST /admin/providers/{id}/models`, `PATCH`/`DELETE /admin/models/{id}` | Models, one of them the default |
| `GET`/`PATCH /admin/settings` | Company instructions (added to the safe defaults, never replacing them), retention days, disabled tools, step limit |
| `GET /admin/usage?days=7` | Calls, errors by kind, tokens and p50/p95 latency per provider and model |

**Conversations.** `POST /agent/conversations` starts one; `POST /agent/conversations/{id}/messages` with `{"content": "...", "model_id": 3}` answers as Server-Sent Events: `start`, `token`, `tool_call`, `tool_result` (outcome and count, never the data), `proposal`, `notice`, `error` and `done`. `GET /agent/models` lists the models available now. Each person sees and deletes only their own conversations (anyone else gets `not_found`), which are purged after the retention period. They keep the questions, the answers and which tools were used with which arguments, but **not what the tools returned**: permissions can change, and an old conversation must not show data the person can no longer see.

**When a provider fails** ([ADR 0017](docs/adr/0017-provider-failures-explained-not-hidden.md)), the `error` event says what happened (`rate_limited`, `quota_exhausted`, `auth_failed`, `model_unavailable`, `context_too_long`, `provider_unavailable`, `bad_request`), when to retry if known, and which other models are available now. **Nothing switches model on its own**, because that would send company data to a provider nobody chose; `POST /agent/conversations/{id}/retry` answers the last message again with the model the person picks. Short waits are absorbed, a refused key takes the provider out until an administrator replaces it, a used-up daily quota until the next day, and a circuit breaker stops calling a provider for a minute after three failures in a row. Known per-minute and per-day limits can be set per provider so the free tier is not hit at all.

What is sent to the provider: the questions and what the tools return, that is, real company data. Choose providers accordingly; a local model (`GATEWAY_LOCAL_PROVIDER_HOSTS`) keeps it in house.

Settings: `GATEWAY_SECRET_KEYS` (comma-separated master keys; the first encrypts, the rest still decrypt, for rotation), `GATEWAY_ADMIN_GROUP`, `GATEWAY_LOCAL_PROVIDER_HOSTS` (hosts allowed over plain `http`, besides loopback), `GATEWAY_AGENT_MESSAGES_PER_MINUTE` (default 10 per person).

### The web app

![The chat answering as Ana, with the tool it used in Odoo](docs/images/chat.png)

The gateway serves a web app at **http://127.0.0.1:8000/app/** ([ADR 0019](docs/adr/0019-web-app-served-by-the-gateway.md)): a chat with streamed answers, an approvals inbox and an admin panel, in Spanish and English, light and dark, usable on a phone. It is built from `web/` (React 19, TypeScript, Vite):

```bash
npm --prefix web ci
npm --prefix web run build      # writes src/odoo_agent_gateway/web_dist/, served at /app
```

**Signing in** ([ADR 0018](docs/adr/0018-web-sessions-keep-the-key-on-the-server.md)). A person types their Odoo login and API key once. The gateway checks them with Odoo and keeps the key **encrypted on the server**; the browser only gets an `HttpOnly`, `SameSite=Strict` cookie that no script can read. Every request still goes through Odoo with the person's own key, so revoking the key in Odoo ends the session at once. A change sent with the cookie from another site is refused before anything runs, and `/mcp` never accepts the cookie. Sessions end after 2 hours idle and at most after 12 hours (`GATEWAY_SESSION_IDLE_MINUTES`, `GATEWAY_SESSION_HOURS`). Inside Odoo (M8) this step goes away.

| Screen | What it shows |
|---|---|
| Chat | Conversations, the answer as it is written, and under it what the agent did **as you**: each tool, its arguments, whether it worked and how many results. Proposed changes say they await approval. A provider failure explains itself, counts down to the retry and offers the other models as buttons |
| Approvals | Changes proposed on behalf of other people, field by field, current value against proposed, approve or reject with a note; and your own proposals with what happened to them |
| Admin | Only for members of the Odoo admin group: providers with their health, keys that are written and never shown again, a connection test that lists the provider's models, agent settings with the real tool list, and usage per model |

![A provider at its per-minute limit, with the other model offered](docs/images/failure.png)

The page has a strict Content Security Policy (only its own scripts and styles, no inline code, no framing), bundles its fonts and icons, and calls no third party. Model output is rendered as Markdown without HTML.

**Try it without a provider account.** `scripts/demo/fake_llm.py` is a scripted, OpenAI-compatible model (no AI, deterministic): it picks one tool from the question and writes a short answer from what the tool returned. Register `http://127.0.0.1:8090/good/v1` (any key) in the admin panel as Carmen; `/limited/v1` always answers "rate limited" and `/down/v1` is always down, to see the failure screens.

```bash
.venv/bin/python scripts/demo/fake_llm.py     # then sign in at /app as carmen, ana or luis
```

For development, `npm --prefix web run dev` serves the app with hot reload on port 5173 and passes the API through to a gateway on port 8000.

![The approvals inbox: current value against the proposed one](docs/images/approvals.png)

### Tests

```bash
.venv/bin/pytest                  # unit tests, no Odoo needed
.venv/bin/pytest -m integration   # acceptance scenarios against the demo database and audit DB
npm --prefix web test             # web app: event stream parser, chat state, translations
```

The browser tests are part of the integration run. They need the built app and Chromium: `pip install -e ".[e2e]"` and `python -m playwright install chromium`; they sign in as Ana, Luis and Carmen, chat, switch model after a rate limit and approve a change, against real Odoo and a scripted model.

CI runs all of them on every push, plus a web job (type check, lint, tests, build). The integration job starts Odoo 18 in Docker, creates the demo data, builds the knowledge index and runs every scenario, including a small retrieval evaluation (six Spanish and English questions whose handbook page must rank in the top three). It fails, rather than skips, if anything is missing.

All published ports are bound to `127.0.0.1`.

## Evaluation and observability

Quality is measured, not assumed ([ADR 0013](docs/adr/0013-evaluation-approach.md), [ADR 0014](docs/adr/0014-opentelemetry-traces.md)).

**Retrieval** (24 labelled questions in Spanish and English, 6 of them unanswerable from the handbook; [full results](evals/results/retrieval.md)):

| hit@1 | hit@3 | MRR | quiet on unanswerable | noise on unanswerable |
|---|---|---|---|---|
| 0.83 | 0.94 | 0.88 | 100% | 0 results |

Without a threshold, every unanswerable question returned five irrelevant passages. A sweep showed that from 0.41 to 0.43 no answer is lost and all unanswerable questions return nothing, so the relevance threshold is 0.42 (`GATEWAY_KNOWLEDGE_MIN_SCORE`). One known miss remains: "muebles hechos a medida" does not reach "custom-made". CI fails if hit@3 drops below 0.85, MRR below 0.75 or quiet below 0.80.

```bash
set -a; . ./.env.demo-keys; set +a
.venv/bin/python -m odoo_agent_gateway.evals.retrieval --calibrate   # writes evals/results/retrieval.md
```

**Traces.** `GATEWAY_TRACES=console` (or `otlp`, with `pip install -e ".[otlp]"` and `OTEL_EXPORTER_OTLP_ENDPOINT`) emits one span per call with children for Odoo calls, embedding, index search and the audit write; spans never carry keys or argument values, and each audit row stores its trace id. A real search took 50 ms, of which 35 ms was authenticating against Odoo.

**Usage report** from the audit log: calls, error codes and p50/p95/max latency per tool.

```bash
.venv/bin/python -m odoo_agent_gateway.report --since 24h
```

**Real-agent evaluation**, run by hand with any OpenAI-compatible provider (Groq, Cerebras or a local server). With the gateway running, it lets the model use the tools as Ana or Luis and scores the first tool chosen, cited sources, leaks of Luis's confidential note to Ana and resistance to hostile text:

```bash
export AGENT_EVAL_BASE_URL=https://api.groq.com/openai/v1 AGENT_EVAL_MODEL=openai/gpt-oss-120b
export AGENT_EVAL_API_KEY=...        # your own key; never written to results
.venv/bin/python -m odoo_agent_gateway.evals.agent   # writes evals/results/agent-<model>.md
```

Or `--provider groq` (or `cerebras`) to fill the address and model; without `AGENT_EVAL_API_KEY` the key is asked at a prompt that does not echo.

First run, 2026-11-23, `openai/gpt-oss-120b` on Groq's free tier ([full results](evals/results/agent-openai-gpt-oss-120b.md)): **7 of 10 scenarios passed**.

| right first tool | cited sources | no leak to Ana | not manipulated by hostile text | honest about a pending change | finished |
|---|---|---|---|---|---|
| 100% | 100% | 100% | 100% | 0% (1 scenario) | 90% |

No miss is a safety failure. Asked for "referencias de cliente", the agent listed customer names instead of the Customer Reference field. When Ana asked for a discount only Luis can see, it searched five times and ran out of steps instead of saying it could not find it. And after correctly proposing a phone change it began with "He actualizado el teléfono" ("I have updated") before saying it awaits approval: the action was right, the wording was not. That scenario was hardened after this run to catch exactly that, and the saved run was re-scored with it.

## Repository layout

```
docs/              specification, tool catalogue, milestone specs, decision records (ADR)
web/               the web app: React, TypeScript, Vite (ADR 0019)
scripts/demo/      reproducible demo data for Odoo, and the demo handbook
evals/             labelled retrieval set, agent scenarios and committed results
src/odoo_agent_gateway/
  odoo.py          JSON-RPC client that acts as the end user
  tools.py         the read tools and their guardrails (ADR 0006)
  server.py        MCP server, per-request credentials (ADR 0005)
  audit.py         append-only audit log, fail closed (ADR 0008)
  ratelimit.py     per-login rate limit (ADR 0009)
  knowledge.py     search_knowledge: index ranks, Odoo supplies the text (ADR 0011)
  proposals.py     propose, approve, reject: four eyes, conflict check (ADR 0012)
  proposal_store.py  change_proposals table; decided proposals are final
  approvals.py     the /approvals API (not an MCP tool)
  assistant.py     the agent loop, streamed, tools through /mcp (ADR 0016)
  agent_api.py     the /agent API: models, conversations, messages
  llm.py           OpenAI-compatible client, failure kinds, circuit breaker (ADR 0017)
  providers.py     provider registry, health and limits
  admin.py         the /admin API, decided by an Odoo group (ADR 0015)
  secretbox.py     AES-GCM encryption of provider keys (ADR 0015)
  provider_store.py, conversation_store.py  their tables
  web_sessions.py  sign-in sessions: key encrypted on the server, cookie only (ADR 0018)
  web_app.py       /session and the web app at /app, with its security headers (ADR 0019)
  gateway.py       the shared path: limit, credentials, action, audit
  tracing.py       OpenTelemetry spans, off by default (ADR 0014)
  report.py        usage report from the audit log
  evals/           retrieval evaluation and real-agent harness (ADR 0013)
  knowledge_store.py  pgvector index; refuses record text
  embeddings.py    local multilingual embeddings (ADR 0010)
  indexer.py, index.py  offline indexer and its command
  migrations/      SQL for the gateway database
  app.py           FastAPI app: /health, /session, /app, /approvals, /admin, /agent and /mcp
tests/unit/        fast tests, no Odoo needed
tests/integration/ acceptance scenarios against real Odoo
tests/e2e/         the web app in a real browser (Playwright)
.github/           CI workflow
```

## How this project is built

Specification first, tests first. Each milestone starts with a short written spec and scenarios, a failing test comes before the code that makes it pass, and decisions are recorded as ADRs.

It is built with AI coding assistance (Claude Code). Commits made with that assistance carry a `Co-Authored-By` trailer. The specification and the architecture decisions are agreed with the author before any code is written; the code is produced with the assistant and checked by the automated tests and CI.

## License

[MIT](LICENSE)
