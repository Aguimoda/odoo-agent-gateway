-- Audit log for every tool call (ADR 0008). Idempotent: safe to run on every start.

create table if not exists audit_log (
  id bigint generated always as identity primary key,
  occurred_at timestamptz not null default now(),
  request_id text,
  login text,                      -- as claimed by the caller; may be wrong or empty
  odoo_uid bigint,                 -- set only when Odoo confirmed the credentials
  tool text not null,
  arguments jsonb not null default '{}'::jsonb,
  outcome text not null check (outcome ~ '^[a-z_]+$'),  -- 'ok' or an error code
  result_count integer check (result_count >= 0),
  duration_ms integer not null check (duration_ms >= 0)
);

create index if not exists audit_log_login_occurred_at_idx
  on audit_log (login, occurred_at desc);

-- Append-only: rows can be inserted and read, never changed or removed.
create or replace function audit_log_reject_change() returns trigger
language plpgsql as $$
begin
  raise exception 'audit_log is append-only: % is not allowed', tg_op;
end;
$$;

create or replace trigger audit_log_no_update_or_delete
  before update or delete on audit_log
  for each row execute function audit_log_reject_change();

-- Row triggers do not fire on TRUNCATE, so it needs its own statement trigger.
create or replace trigger audit_log_no_truncate
  before truncate on audit_log
  for each statement execute function audit_log_reject_change();
