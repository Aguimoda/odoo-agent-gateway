-- Web sessions (ADR 0018): the browser holds only a random session id in an HttpOnly
-- cookie; the server keeps its SHA-256 and the person's Odoo key, encrypted with the
-- master keys and bound to that id.

create table if not exists web_sessions (
  id_hash bytea primary key check (octet_length(id_hash) = 32),
  odoo_uid integer not null,
  login text not null,
  key_encrypted bytea not null,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  expires_at timestamptz not null
);

create index if not exists web_sessions_expires_at on web_sessions (expires_at);
