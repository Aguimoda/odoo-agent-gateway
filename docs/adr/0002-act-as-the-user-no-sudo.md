# 2. Act as the end user through Odoo; never use a privileged account

Date: 2026-11-22. Status: accepted.

## Context

An AI agent that reads and proposes changes in an ERP must not be able to see or touch more than the person using it. The easy design, one service account with broad rights, turns the gateway into a confused deputy: any user could obtain through the agent what Odoo itself would refuse them.

Odoo already has the access model that matters: access rights per model, record rules and field-level groups. Odoo 18 lets each user create a personal API key that is accepted in place of a password on its external JSON-RPC interface.

## Decision

The gateway authenticates to Odoo **with the API key of the person asking**, so Odoo evaluates every request as that person. The gateway holds no administrator credentials and never uses `sudo` or an equivalent. The gateway does not re-implement permission logic: Odoo remains the single source of truth.

## Consequences

- A user who cannot read a record in Odoo cannot read it through the agent. This is testable with two demo users of different rights.
- Each user must provide an API key. Key storage, rotation and revocation become part of the gateway design (handled in milestone M1).
- Performance depends on Odoo's own JSON-RPC speed. Accepted for version 1.
- The RAG index (M3) cannot be shared across users blindly: every result is re-checked against Odoo for the asking user before it is returned.
