# 21. Inside Odoo: a short-lived key the person's module creates, handed over as a one-time ticket

Date: 2026-11-23. Status: accepted.

## Context

M8 brings the assistant into Odoo. The product plan (decision 2) already settled that the engine stays outside Odoo, holding only the person's own key, and that inside Odoo the person should not paste a key: the module creates a short-lived one, with consent, renews it and lets the person revoke it.

Checked against Odoo 18 Community (`base/models/res_users.py`): `res.users.apikeys._generate(scope, name, expiration_date)` creates a key for the current user; without sudo the expiration is required and limited to the longest `api_key_duration` of the user's groups (1 day by default); expired keys are refused by `_check_credentials` and deleted by an autovacuum. A key can be limited to the `rpc` scope, which is what the gateway uses.

The web app keeps the key on the server and gives the browser only an `HttpOnly`, `SameSite=Strict` cookie (ADR 0018), and forbids framing (`frame-ancestors 'none'`, ADR 0019).

## Decision

- The Odoo module `agent_gateway_connector` creates the key **as the person, without sudo**: name "Odoo Agent Gateway (assistant)", scope `rpc`, expiring after 8 hours, only after the person has accepted a consent notice. It renews the key when it has less than an hour left and deletes the previous one. "Revoke" deletes all of the person's assistant keys; the gateway session stops working at once because every request goes through Odoo with that key.
- Odoo's server sends the login and key to the gateway's `POST /session/ticket` (server to server). The gateway checks them with Odoo, opens a web session as in ADR 0018 and returns a random **one-time ticket**, stored only as a SHA-256 hash and valid for 60 seconds.
- The browser opens the gateway's web app in a side panel inside Odoo. The ticket travels in the URL **fragment** (`#ticket=…`), which browsers never send to servers, so it cannot reach access logs; the page posts it to `POST /session/redeem`, which sets the usual cookie.
- The gateway allows framing only by the origins in `GATEWAY_EMBED_ORIGINS` (`frame-ancestors`); the default stays "none".
- The panel reuses the web app of M7 in a compact mode, instead of a second chat written with Odoo's OWL components.
- Deployment requirement: Odoo and the gateway on the same site (same registrable domain, or the gateway behind Odoo), because the cookie is `SameSite=Strict` and browsers block third-party cookies.

## Consequences

- The person never sees or pastes a key; the key never reaches the browser; Odoo's own limits on key duration apply, and an administrator can see and delete assistant keys like any other.
- The module adds no privileged path: everything it does in Odoo is done as the person (checked by a test).
- One chat implementation serves both the standalone web app and Odoo, so fixes land in both.
- A ticket leaked within its 60 seconds could open a session once; the fragment, the hash and the single use keep that window small.
- Odoo and the gateway must share a site; a fully separate domain would need a different session mechanism (for example partitioned cookies), left out for now.
