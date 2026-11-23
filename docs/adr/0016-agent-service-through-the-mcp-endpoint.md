# 16. Agent service: tools through the gateway's own MCP endpoint, streamed answers, private conversations

Date: 2026-11-23. Status: accepted.

## Context

Until M5 the agent loop only existed in the evaluator. People need it as a service: send a message, watch the answer being written, come back to the conversation later. The plan (docs/PRODUCT-PLAN.md) keeps the engine outside Odoo, so it never holds more than the person's own key and slow model calls never block Odoo workers.

## Decision

**Tools**
- The agent calls tools by sending MCP requests to the gateway's own `/mcp` endpoint, in process (an ASGI transport, no network), with the person's own credentials. Each tool call therefore takes exactly the path an external agent takes: rate limit, Odoo authentication, guardrails, fail-closed audit. There is no second, privileged route to Odoo.
- Administrators can disable tools for the agent; the safe default instructions cannot be removed, only added to.

**Answers**
- `POST /agent/conversations/{id}/messages` answers with Server-Sent Events: `token`, `tool_call`, `tool_result` (outcome and count, not the data), `proposal`, `notice`, `error` and `done`.
- The default instructions carry two lessons from the real-agent evaluation (ADR 0013): say plainly when something was not found, and never claim a change was made, only that it was proposed and awaits approval. When the step limit is reached, the model is asked once more, without tools, to answer with what it has.
- Messages per person and minute are limited (`GATEWAY_AGENT_MESSAGES_PER_MINUTE`), on top of the per-login limit that every tool call already counts against.

**Conversations**
- Stored in the gateway's PostgreSQL, owned by the Odoo user id that Odoo authenticated. Anyone else gets `not_found`, administrators included. Owners can delete theirs.
- Stored: the person's messages, the answers, and the names and arguments of the tools used. **Not stored: what the tools returned.** Tool results are Odoo data read with the person's rights at that moment; replaying them later would show data their rights may no longer allow. Only the answers' text is sent back to the model as history.
- Deleted automatically after the retention period (30 days by default, set by administrators).

## Consequences

- Every tool call made by the chat is audited like any other, so the audit log already answers "what did the assistant do as Ana?".
- Questions and tool results are sent to the configured provider: that is real company data, and the admin API names the provider each model belongs to. A local model keeps the data in house.
- An in-process MCP round trip costs a little serialisation; the measured cost of a tool call is Odoo authentication (ADR 0014), not this.
