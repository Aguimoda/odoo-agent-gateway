# Odoo Agent Gateway

A permission-aware [MCP](https://modelcontextprotocol.io) gateway that lets AI agents work on Odoo **as the person asking, never as an administrator**.

> **Status: milestone M1 done (version 0.1.0).** The six read tools work over MCP, each call runs with the caller's own Odoo API key, and the permission scenarios pass against a real Odoo 18. Not production-ready yet: audit log, retrieval, approved writes and deployment come in later milestones.

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
- **Provable.** Permission-leak checks run in CI with two demo users of different rights.

## Version 1 tools

| Tool | Purpose | Milestone |
|---|---|---|
| `my_permissions` | What the asking user may see and do | M1 |
| `list_models` | Accessible data areas | M1 |
| `describe_model` | Fields of a data area | M1 |
| `search_records` | Filtered search | M1 |
| `read_record` | One record | M1 |
| `summarize_data` | Counts and sums, grouped | M1 |
| `search_knowledge` | Retrieval over documentation and visible records, with sources | M3 |
| `propose_change` | Propose a write; a human approves it | M4 |
| `list_my_proposals` | Status of the user's proposals | M4 |

Deliberately not offered: deleting records, free-form SQL, calling arbitrary Odoo methods, privileged accounts, and changes without human approval. Details in [docs/TOOLS.md](docs/TOOLS.md) (Spanish).

## Roadmap

| Milestone | Delivers | Status |
|---|---|---|
| M0 | Repository, specification, decisions, local stack, CI | Done |
| M1 | Read-only MCP server using each user's Odoo API key, test-first | Done |
| M2 | Permission-leak test suite in CI and audit log | Next |
| M3 | Retrieval with pgvector, filtered by permissions | |
| M4 | Write proposals with human approval | |
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

python scripts/demo/setup_demo.py  # demo database with users "ana" and "luis"
```

`setup_demo.py` creates a `demo` database with the Sales app and two users: **Ana** (sales, sees only her own orders) and **Luis** (sales administrator, sees everything). Their API keys, their order ids and a random password for the demo administrator are written to `.env.demo-keys`, which git ignores. Odoo's default admin password is not kept.

### Start the gateway

```bash
export ODOO_URL=http://127.0.0.1:8069 ODOO_DB=demo
.venv/bin/python -m odoo_agent_gateway   # MCP endpoint on http://127.0.0.1:8000/mcp
```

An MCP client connects to `http://127.0.0.1:8000/mcp` with two headers per request (ADR 0005):

```
X-Odoo-Login: ana
Authorization: Bearer <Ana's Odoo API key>
```

The gateway stores no credentials; Odoo checks them on every call.

Optional settings: `GATEWAY_ALLOWED_MODELS` (comma-separated, default contacts, products and sales), `GATEWAY_ALLOWED_HOSTS` and `GATEWAY_ALLOWED_ORIGINS` (default local only), `GATEWAY_HOST` and `GATEWAY_PORT`.

### Tests

```bash
.venv/bin/pytest                  # unit tests, no Odoo needed
.venv/bin/pytest -m integration   # acceptance scenarios against the demo database
```

All published ports are bound to `127.0.0.1`.

## Repository layout

```
docs/              specification, tool catalogue, milestone specs, decision records (ADR)
scripts/demo/      reproducible demo data for Odoo
src/odoo_agent_gateway/
  odoo.py          JSON-RPC client that acts as the end user
  tools.py         the read tools and their guardrails (ADR 0006)
  server.py        MCP server, per-request credentials (ADR 0005)
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
