-- Write proposals awaiting a second person's approval (ADR 0012). Idempotent.

create table if not exists change_proposals (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  proposer_login text not null,
  proposer_uid bigint not null,
  model text not null,
  record_id bigint not null check (record_id > 0),
  changes jsonb not null,           -- the new values the proposer typed
  before_hash text not null,        -- fingerprint of the values at proposal time, not the values
  reason text not null check (char_length(reason) between 10 and 500),
  status text not null default 'pending'
    check (status in ('pending', 'applied', 'rejected', 'conflict', 'failed', 'expired')),
  decided_at timestamptz,
  decider_login text,
  decider_uid bigint,
  decision_note text check (decision_note is null or char_length(decision_note) <= 500),
  error_code text,
  constraint change_proposals_decision_shape check (
    (status = 'pending') = (decided_at is null)
  )
);

create index if not exists change_proposals_pending_idx
  on change_proposals (created_at) where status = 'pending';

create index if not exists change_proposals_proposer_idx
  on change_proposals (proposer_uid, created_at desc);

-- A proposal's content never changes, a decided proposal is final, nothing is deleted.
create or replace function change_proposals_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'change_proposals: proposals are never deleted';
  end if;
  if old.status <> 'pending' then
    raise exception 'change_proposals: proposal % is already decided', old.id;
  end if;
  if (new.created_at, new.proposer_login, new.proposer_uid, new.model, new.record_id,
      new.changes, new.before_hash, new.reason)
     is distinct from
     (old.created_at, old.proposer_login, old.proposer_uid, old.model, old.record_id,
      old.changes, old.before_hash, old.reason) then
    raise exception 'change_proposals: the content of a proposal cannot change';
  end if;
  return new;
end;
$$;

create or replace trigger change_proposals_guard
  before update or delete on change_proposals
  for each row execute function change_proposals_guard();

create or replace function change_proposals_reject_truncate() returns trigger
language plpgsql as $$
begin
  raise exception 'change_proposals: truncate is not allowed';
end;
$$;

create or replace trigger change_proposals_no_truncate
  before truncate on change_proposals
  for each statement execute function change_proposals_reject_truncate();
