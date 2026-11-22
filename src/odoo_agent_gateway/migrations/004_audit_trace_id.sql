-- Link each audit row to its OpenTelemetry trace (ADR 0014). Idempotent.
-- Adding a column is not an UPDATE: the append-only triggers on audit_log are unaffected.

alter table audit_log add column if not exists trace_id text
  check (trace_id is null or trace_id ~ '^[0-9a-f]{32}$');
