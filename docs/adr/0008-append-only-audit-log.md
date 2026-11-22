# 8. Append-only audit log in the gateway database; fail closed

Date: 2026-11-22. Status: accepted.

## Context

When an agent reads business data on someone's behalf, the organisation needs to answer afterwards: who asked what, when, through which tool, and what came back. Odoo's own logs do not show that a request came through an agent, nor the tool and arguments the agent chose.

## Decision

- Every tool call writes one row to `audit_log` in the gateway's PostgreSQL (ADR 0004), including failed authentication, guardrail errors and rate-limited calls.
- A row holds: time, request id, the login the caller claimed, the Odoo user id when Odoo confirmed it, tool name, tool arguments (as JSON, cut at 4,000 characters), outcome (`ok` or the error code), number of records or groups returned, and duration in milliseconds.
- **Never stored:** API keys, the `Authorization` header, or the data returned to the agent.
- The table is **append-only**: a database trigger rejects `UPDATE` and `DELETE`.
- The gateway **fails closed**: if the row cannot be written, the call returns `audit_unavailable` and no data.

## Consequences

- Every answer the agent got can be traced to a person and a request.
- The gateway depends on its database being available. Accepted: an unaudited answer is worse than no answer.
- Arguments may contain business values used as filters (a customer name). Accepted and documented; returned data is not logged.
- The table grows without limit; retention and archiving are a later decision.
- A database superuser can still drop the trigger. The trigger protects against the application and casual edits, not against an administrator.
