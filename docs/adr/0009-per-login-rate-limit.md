# 9. Per-login rate limit, applied before calling Odoo

Date: 2026-11-22. Status: accepted.

## Context

An agent in a loop, or someone guessing API keys, can send many calls quickly. Each call costs at least one authentication round trip to Odoo (ADR 0005).

## Decision

- Limit calls per **claimed login** to `GATEWAY_RATE_LIMIT_PER_MINUTE` (default 60) over a sliding one-minute window.
- Check the limit **before** contacting Odoo, so rejected calls cost Odoo nothing and failed key guesses count against the login being attacked.
- Calls without a login share one `anonymous` bucket.
- Over the limit, the call fails with `rate_limited` and is audited (ADR 0008).
- The counter lives in the memory of each gateway process.

## Consequences

- Simple, with no extra infrastructure.
- With several gateway instances, the effective limit is the per-process limit times the number of instances. Moving the counter to PostgreSQL or Redis is the upgrade path if the gateway is scaled out.
- An attacker can make a legitimate user hit the limit by sending calls with that user's login. Accepted for version 1: the limit window is short and those calls are audited.
