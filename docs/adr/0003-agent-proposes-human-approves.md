# 3. The agent only proposes changes; a human approves through a separate channel

Date: 2026-11-22. Status: accepted.

## Context

Letting a language model write to an ERP directly risks wrong or manipulated changes, for example text inside a record that tells the agent to edit something. Some work still needs write access, so a read-only gateway would be too limited.

## Decision

Write access goes through a proposal. The agent calls `propose_change`, which stores the intended change and its reason and returns a proposal id. **Approving is not an agent tool.** A person approves or rejects through a separate interface (a small web endpoint or command line), and the gateway re-checks with Odoo, as that person, that the change is allowed before executing it.

Not offered in version 1: deleting records, arbitrary SQL, calling arbitrary Odoo methods.

## Consequences

- The agent cannot approve its own proposals, even if manipulated.
- Every change has a named approver and an audit entry.
- Writing becomes slower than direct execution. Accepted: the control is the point.
- A proposals store and an approval interface must be built (milestone M4).
