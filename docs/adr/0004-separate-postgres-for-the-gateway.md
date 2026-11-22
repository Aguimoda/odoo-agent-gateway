# 4. Use a separate PostgreSQL instance with pgvector for the gateway

Date: 2026-11-22. Status: accepted.

## Context

The gateway needs its own storage: audit log, proposals and, from milestone M3, a vector index for retrieval. Odoo has its own PostgreSQL database, managed by Odoo.

## Decision

Run two PostgreSQL services in Docker Compose: the one Odoo uses, and a separate one for the gateway based on the `pgvector/pgvector` image. The gateway never connects to Odoo's database directly; it reaches Odoo only through its external API (see ADR 0002).

## Consequences

- No coupling to Odoo's schema or migrations, and no way to bypass Odoo's permission model through SQL.
- The gateway database can be backed up, reset or replaced without touching Odoo.
- One more container to run locally. Accepted.
