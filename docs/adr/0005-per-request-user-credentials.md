# 5. Per-request user credentials; the gateway stores none

Date: 2026-11-22. Status: accepted. May be superseded by an OAuth 2 decision in a later milestone.

## Context

ADR 0002 requires every Odoo call to be made with the asking user's own API key. The gateway therefore needs that key on each request. Options considered:

1. The gateway stores each user's key and maps its own token to it. Needs secure storage, rotation and a sign-up flow.
2. The MCP client sends the user's Odoo login and API key with each request, and the gateway forwards them to Odoo, which validates them.
3. Full OAuth 2 with the gateway as a resource server. The right long-term answer, but it needs an authorization server and token exchange that Odoo Community does not provide out of the box.

## Decision

Version 1 uses option 2. Each HTTP request to `/mcp` carries:

- `X-Odoo-Login: <user login>`
- `Authorization: Bearer <that user's Odoo API key>`

The gateway treats both as untrusted input. It calls Odoo's `authenticate` with them on every tool call, and proceeds only with the user id Odoo returns. It never writes the key to disk, logs or the database.

## Consequences

- Nothing secret is stored by the gateway, so there is nothing to leak from it at rest.
- Revoking a key in Odoo cuts access immediately.
- One extra round trip to Odoo per tool call. Accepted for version 1; a short-lived in-memory cache can be added later if needed.
- The key travels on every request, so outside local development the gateway must sit behind HTTPS. This is required for the M6 deployment.
- Logs and error messages must never echo the `Authorization` header. Covered by tests.
