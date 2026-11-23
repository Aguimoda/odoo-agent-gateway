-- Agent service (ADR 0015, 0016, 0017): providers, models, usage, settings, conversations.
-- Idempotent.

create table if not exists llm_providers (
  id bigint generated always as identity primary key,
  name text not null unique check (name ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
  base_url text not null check (char_length(base_url) <= 300),
  api_key_encrypted bytea,          -- AES-GCM, bound to base_url (ADR 0015); never returned
  key_updated_at timestamptz,
  enabled boolean not null default true,
  requests_per_minute integer check (requests_per_minute is null or requests_per_minute > 0),
  requests_per_day integer check (requests_per_day is null or requests_per_day > 0),
  auth_failed_at timestamptz,       -- set on 401/403, cleared when the key is replaced
  exhausted_until timestamptz,      -- daily quota used up
  last_error_kind text,
  last_error_at timestamptz,
  last_ok_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists llm_models (
  id bigint generated always as identity primary key,
  provider_id bigint not null references llm_providers (id) on delete cascade,
  name text not null check (char_length(name) between 1 and 200),
  label text check (label is null or char_length(label) <= 100),
  enabled boolean not null default true,
  is_default boolean not null default false,
  unavailable_at timestamptz,       -- the provider said the model does not exist
  created_at timestamptz not null default now(),
  unique (provider_id, name)
);

-- At most one default model.
create unique index if not exists llm_models_one_default on llm_models ((true)) where is_default;

-- One row per call to a provider. Names, not ids, so history survives deleting a provider.
create table if not exists llm_usage (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  provider text not null,
  model text not null,
  login text,
  outcome text not null,            -- ok or a failure kind (ADR 0017)
  prompt_tokens integer,
  completion_tokens integer,
  latency_ms integer not null
);

create index if not exists llm_usage_provider_at_idx on llm_usage (provider, at);
create index if not exists llm_usage_at_idx on llm_usage (at);

-- A single row of settings that administrators change through /admin/settings.
create table if not exists agent_settings (
  id boolean primary key default true check (id),
  instructions text not null default '' check (char_length(instructions) <= 4000),
  retention_days integer not null default 30 check (retention_days between 1 and 3650),
  disabled_tools text[] not null default '{}',
  max_steps integer not null default 6 check (max_steps between 1 and 20),
  updated_at timestamptz not null default now(),
  updated_by text
);

insert into agent_settings (id) values (true) on conflict (id) do nothing;

create table if not exists conversations (
  id uuid primary key default gen_random_uuid(),
  owner_uid bigint not null,        -- the Odoo user id that Odoo authenticated
  owner_login text not null,
  title text not null check (char_length(title) <= 120),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists conversations_owner_idx on conversations (owner_uid, updated_at desc);
create index if not exists conversations_updated_idx on conversations (updated_at);

-- What tools returned is deliberately not stored (ADR 0016): only their names and arguments.
create table if not exists conversation_messages (
  id bigint generated always as identity primary key,
  conversation_id uuid not null references conversations (id) on delete cascade,
  at timestamptz not null default now(),
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  tools jsonb not null default '[]'::jsonb,
  model text,
  status text not null default 'complete' check (status in ('complete', 'incomplete', 'error')),
  error_kind text
);

create index if not exists conversation_messages_conversation_idx
  on conversation_messages (conversation_id, id);
