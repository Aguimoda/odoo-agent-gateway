# 11. The index only ranks; Odoo, as the user, supplies every record text

Date: 2026-11-22. Status: accepted.

## Context

A shared vector index is the classic way retrieval leaks data: it is built once from many users' records, then queried by everyone. ADR 0002 already says results must be re-checked against Odoo for the asking user. Two more risks remain: stale text (a note changed or removed after indexing) and field-level restrictions (a user may see a record but not one of its fields).

Building the index also needs to read records across users, which seems to require a privileged account.

## Decision

- **Records are indexed as vectors plus a reference** (model, record id, field). Their text is **not stored** in the gateway database.
- At query time: embed the question, take the nearest candidates (up to 100), then ask Odoo **as the asking user** which of those records exist and are visible (`search` on their ids), and **read the field as that user**. Only what Odoo returns is shown, and it is the current text. A record or field Odoo refuses is dropped silently.
- **Company documents** (the demo handbook) are stored with their text: every authenticated user may read them.
- The index is built by a **separate command** (`python -m odoo_agent_gateway.index`) using a dedicated Odoo user, `indexer`, with read access to the indexed models and no administrator rights. Its key is given only to that command, never to the gateway process.

## Consequences

- The index cannot leak record text, even if the gateway database is copied: it holds no record text.
- Answers are never stale, and field-level restrictions are respected, because the text comes from Odoo at query time.
- Each search costs a few extra Odoo calls (one `search` and one `read` per model among the candidates).
- If many hidden records rank above visible ones, visible results can fall outside the candidate window. That loses recall but leaks nothing; the window is 100 candidates.
- The `indexer` account can read more than most users. It is used only offline, only for reading, and its key never reaches the gateway.
