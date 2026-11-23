-- Token budget and provider error codes (ADR 0020).
-- tokens_per_minute: the provider's known limit, checked before calling it.
-- error_code: the provider's short error code for a failed call (never its message).

alter table llm_providers add column if not exists tokens_per_minute integer;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'llm_providers_tokens_per_minute_positive'
  ) then
    alter table llm_providers add constraint llm_providers_tokens_per_minute_positive
      check (tokens_per_minute is null or tokens_per_minute > 0);
  end if;
end $$;

alter table llm_usage add column if not exists error_code text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'llm_usage_error_code_short') then
    alter table llm_usage add constraint llm_usage_error_code_short
      check (error_code is null or char_length(error_code) <= 80);
  end if;
end $$;
