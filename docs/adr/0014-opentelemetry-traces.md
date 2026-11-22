# 14. OpenTelemetry traces, off by default, linked from the audit log

Date: 2026-11-23. Status: accepted.

## Context

The audit log records each call and its total duration (ADR 0008), but not where the time goes: Odoo authentication, Odoo calls, the embedding model, the vector index. OpenTelemetry is the standard way to record that, and its API is already a dependency of the MCP SDK.

## Decision

- Wrap each call in a span (`gateway.<tool>`) with child spans for authentication, each Odoo RPC (service, method, model), embedding and index search.
- Span attributes carry the tool, the outcome code, the Odoo model and method, never credentials, arguments' values or returned data.
- Exporting is **off by default**. `GATEWAY_TRACES=console` prints spans; `GATEWAY_TRACES=otlp` sends them to the endpoint in the standard `OTEL_EXPORTER_OTLP_ENDPOINT`.
- The audit row stores the trace id, so a row can be joined to its trace.

## Consequences

- No overhead beyond the no-op API when tracing is off.
- With OTLP, traces can be explored in any compatible backend (Jaeger, Grafana Tempo, Azure Monitor).
- One more column in `audit_log` (added by a migration; existing rows have none).
