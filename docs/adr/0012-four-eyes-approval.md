# 12. Four-eyes approval, executed as the approver

Date: 2026-11-23. Status: accepted. Refines ADR 0003.

## Context

ADR 0003 says the agent only proposes and a person approves through a separate channel. But the agent holds the API key of the person using it (ADR 0005). Any approval channel that accepts that same key is reachable by the agent, so letting people approve their own proposals would let their agent approve them too.

When the change is finally written, it must respect Odoo's rules for the person who allowed it, and it must not overwrite something that changed meanwhile.

## Decision

- **Nobody approves their own proposal.** The approver must be a different Odoo user (compared by the user id Odoo confirms, not by the login header). Otherwise the result is `four_eyes`.
- **Approval is not an MCP tool.** It lives at `/approvals`, a small HTTP API next to `/mcp`, authenticated with the approver's own Odoo login and API key.
- **The write runs as the approver.** Odoo applies the approver's access rights, record rules and field groups at that moment. Odoo errors make the proposal `failed`, with the error code kept.
- **Optimistic concurrency.** At proposal time the gateway stores a SHA-256 fingerprint of the current values of the fields to change. At approval it re-reads them as the approver; if the fingerprint differs, the result is `conflict` and nothing is written.
- **Minimal copies of Odoo data.** A proposal stores the new values the person typed and the reason, not the old values. Approvers see the current values read live from Odoo.
- **Narrow writes.** Only existing records, at most 10 fields, simple field types (text, number, date, boolean, selection, many2one). Never state, company, `active` (archiving), x2many lists, binary fields or read-only fields.
- **Decisions are final.** Pending proposals expire after 7 days. A database trigger forbids changing the content of a proposal and any change to a decided one. Proposals, approvals and rejections are audited (ADR 0008).

## Consequences

- An agent cannot get a change applied without a second person.
- Single-person teams cannot use write proposals. Accepted: the control is the point.
- Odoo and the gateway database are separate systems. If the gateway stopped right after Odoo accepted a write and before the status was saved, the proposal would stay pending; approving it again would then end in `conflict`, never in a double write.
- A second person's own agent could, in principle, call the approval API with that person's key. The API is not exposed as a tool, and every decision is audited with the approver's identity. A session-based approval screen with a stronger login is the upgrade path (M6).
