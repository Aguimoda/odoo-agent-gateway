# 6. Guardrails for the read tools

Date: 2026-11-22. Status: accepted.

## Context

Odoo enforces permissions (ADR 0002), but an agent can still cause harm with valid permissions: dumping large volumes of data, probing related records through search filters, or receiving text crafted to manipulate it. The gateway should add a thin, predictable layer on top of Odoo, without re-implementing Odoo's permission model.

## Decision

- **Model allowlist.** Tools work only on models listed in configuration (`GATEWAY_ALLOWED_MODELS`). Anything else is rejected before calling Odoo. The default list covers contacts, products and sales.
- **Simple field names only in filters.** Domain conditions must be `[field, operator, value]` with a plain field name (no dotted paths such as `partner_id.name`) and an operator from a fixed list. Logical operators `&`, `|`, `!` are allowed.
- **Size limits.** At most 50 records and 20 fields per call (default 20 records), at most 50 groups in summaries, and text values longer than 2,000 characters are cut and flagged.
- **Explicit fields.** If the agent does not name fields, only `id` and `display_name` are returned, never every field.
- **Clear error codes.** Errors come back as `unauthenticated`, `forbidden`, `not_found` or `invalid_request` with a short message. Odoo internals and credentials are never included.
- **Data is data.** Tool descriptions and the server instructions state that values returned from Odoo are untrusted content, not instructions.

## Consequences

- Some legitimate queries need two steps (look up a partner id, then filter by it). Accepted: it closes the dotted-path probing route.
- The allowlist must be maintained when new modules are exposed.
- Prompt-injection resistance is only partly addressed here; M2 adds hostile-record tests.
