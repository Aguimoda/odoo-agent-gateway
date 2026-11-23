# 18. Web sessions keep the Odoo key on the server

Date: 2026-11-23. Status: accepted.

## Context

M7 adds a web chat, an approvals inbox and an admin panel. Every call still has to run as the person, with their own Odoo API key (ADR 0002, ADR 0005). Agents send that key in headers on every request; a browser page cannot do that safely. If the page held the key in JavaScript (memory, `localStorage`, `sessionStorage`), any script injection would read it, and a key in `localStorage` outlives the tab. Inside Odoo (M8) the module will create a short-lived key on its own; until then, the person types a key once.

## Decision

- `POST /session` takes `{login, api_key}`. The gateway checks them with Odoo on the shared `Gateway.execute` path (rate limit by login, audit row `session.create` without the key), then stores a session row: the SHA-256 of a random 256-bit session id, the Odoo uid and login, and the key **encrypted with the master keys** of ADR 0015, bound to that session id as associated data.
- The browser gets only the session id, in a cookie: `HttpOnly` (no script can read it), `SameSite=Strict` (other sites cannot make the browser send it), `Path=/`, and `Secure` when the request came over HTTPS or `GATEWAY_COOKIE_SECURE=true`. The key never goes back to the browser.
- A middleware turns a valid session into the same `X-Odoo-Login` and `Authorization` headers an agent would send, for `/agent`, `/approvals`, `/admin` and `/session` only. Everything after that is unchanged: Odoo authenticates the key on every request, so revoking the key in Odoo ends the session at once. Requests that carry their own `Authorization` header are left alone. **`/mcp` never accepts the cookie.**
- Cross-site protection twice over: `SameSite=Strict`, and for every cookie-authenticated request that is not `GET`, `HEAD` or `OPTIONS` the `Origin` header must be one of the gateway's own (`GATEWAY_ALLOWED_ORIGINS`, or the request's own host). Otherwise the answer is `403 forbidden` before Odoo is called.
- Sessions end after 2 hours idle (`GATEWAY_SESSION_IDLE_MINUTES`) and at most 12 hours after login (`GATEWAY_SESSION_HOURS`). `DELETE /session` deletes the row and clears the cookie. Expired rows are purged on each login.
- `GET /session` tells the page who is signed in and whether Odoo puts them in the admin group, so the page can hide the admin panel. Hiding is only convenience: the admin API keeps checking the group itself.

## Consequences

- A cross-site scripting bug cannot steal the key or the session id; it could still act while the page is open, which the strict Content Security Policy of ADR 0019 makes much harder.
- A copy of the database without the master keys exposes no keys; session ids are stored only as hashes.
- One database read per web request, plus the Odoo authentication that every request already pays.
- People still create an API key in Odoo once. M8 removes that step.
