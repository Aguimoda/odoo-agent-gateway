# Odoo Agent Gateway

[![CI](https://github.com/Aguimoda/odoo-agent-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/Aguimoda/odoo-agent-gateway/actions/workflows/ci.yml)

A permission-aware [MCP](https://modelcontextprotocol.io) gateway that lets AI agents work on Odoo **as the person asking, never as an administrator**.

> **Status: milestone M3 done (version 0.3.0).** Seven read tools work over MCP, including permission-safe retrieval over a company handbook and Odoo texts. Each call runs with the caller's own Odoo API key, is written to an append-only audit log and is rate-limited per login. The permission-leak suite, retrieval included, runs in CI against a real Odoo 18 on every push. Not production-ready yet: approved writes, broader evaluation and deployment come in later milestones.

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
- **Proposes, never executes.** The agent can only propose a change. A person approves it through a separate channel, and Odoo re-checks the permission at that moment ([ADR 0003](docs/adr/0003-agent-proposes-human-approves.md)).
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
| `propose_change` | Propose a write; a human approves it | M4 |
| `list_my_proposals` | Status of the user's proposals | M4 |

Deliberately not offered: deleting records, free-form SQL, calling arbitrary Odoo methods, privileged accounts, and changes without human approval. Details in [docs/TOOLS.md](docs/TOOLS.md) (Spanish).

## Roadmap

| Milestone | Delivers | Status |
|---|---|---|
| M0 | Repository, specification, decisions, local stack, CI | Done |
| M1 | Read-only MCP server using each user's Odoo API key, test-first | Done |
| M2 | Audit log, rate limits, permission-leak suite in CI against real Odoo | Done |
| M3 | Retrieval with pgvector, filtered by permissions | Done |
| M4 | Write proposals with human approval | Next |
| M5 | Evaluation suites and traces | |
| M6 | Cloud deployment with a public demo, and a short video | |

The full plan, threat model and evaluation design are in [docs/SPEC.md](docs/SPEC.md) (Spanish).

## Run it locally

Requirements: Docker with Compose, and Python 3.11 or newer.

```bash
cp .env.example .env               # then replace every placeholder password
docker compose up -d               # Odoo 18 on http://127.0.0.1:8069 plus two PostgreSQL databases

python -m venv .venv
.venv/bin/pip install -e ".[dev]"  # on Windows: .venv\Scripts\pip

python scripts/demo/setup_demo.py  # demo database with users "ana", "luis" and "indexer"

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

Optional settings: `GATEWAY_RATE_LIMIT_PER_MINUTE` (default 60 per login), `GATEWAY_MODEL_CACHE` (default `.cache/models`), `GATEWAY_ALLOWED_MODELS` (comma-separated, default contacts, products and sales), `GATEWAY_ALLOWED_HOSTS` and `GATEWAY_ALLOWED_ORIGINS` (default local only), `GATEWAY_HOST` and `GATEWAY_PORT`.

### Audit log

Each tool call writes one row to `audit_log`: time, request id, the login the caller claimed, the Odoo user id when Odoo confirmed it, tool, arguments, outcome (`ok` or an error code such as `unauthenticated`, `forbidden` or `rate_limited`), number of records returned and duration. API keys and returned data are never stored, and the table rejects `UPDATE`, `DELETE` and `TRUNCATE`.

### Tests

```bash
.venv/bin/pytest                  # unit tests, no Odoo needed
.venv/bin/pytest -m integration   # acceptance scenarios against the demo database and audit DB
```

CI runs both on every push. The integration job starts Odoo 18 in Docker, creates the demo data, builds the knowledge index and runs every scenario, including a small retrieval evaluation (six Spanish and English questions whose handbook page must rank in the top three). It fails, rather than skips, if anything is missing.

All published ports are bound to `127.0.0.1`.

## Repository layout

```
docs/              specification, tool catalogue, milestone specs, decision records (ADR)
scripts/demo/      reproducible demo data for Odoo, and the demo handbook
src/odoo_agent_gateway/
  odoo.py          JSON-RPC client that acts as the end user
  tools.py         the read tools and their guardrails (ADR 0006)
  server.py        MCP server, per-request credentials (ADR 0005)
  audit.py         append-only audit log, fail closed (ADR 0008)
  ratelimit.py     per-login rate limit (ADR 0009)
  knowledge.py     search_knowledge: index ranks, Odoo supplies the text (ADR 0011)
  knowledge_store.py  pgvector index; refuses record text
  embeddings.py    local multilingual embeddings (ADR 0010)
  indexer.py, index.py  offline indexer and its command
  migrations/      SQL for the gateway database
  app.py           FastAPI app: /health and /mcp (ADR 0007)
tests/unit/        fast tests, no Odoo needed
tests/integration/ acceptance scenarios against real Odoo
.github/           CI workflow
```

## How this project is built

Specification first, tests first. Each milestone starts with a short written spec and scenarios, a failing test comes before the code that makes it pass, and decisions are recorded as ADRs.

It is built with AI coding assistance (Claude Code). Commits made with that assistance carry a `Co-Authored-By` trailer. The specification and the architecture decisions are agreed with the author before any code is written; the code is produced with the assistant and checked by the automated tests and CI.

## License

[MIT](LICENSE)
