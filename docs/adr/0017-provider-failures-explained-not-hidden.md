# 17. Provider failures are classified and explained; the person chooses another model

Date: 2026-11-23. Status: accepted.

## Context

Free tiers run out (Groq and Cerebras have per-minute and per-day limits), keys expire, models are retired, providers go down. A chat that just says "error" is unusable, and a chat that silently switches to another provider sends company data somewhere the person did not choose.

## Decision

- Every provider failure is classified as one of: `rate_limited` (429), `quota_exhausted` (429 mentioning a daily or quota limit), `auth_failed` (401, 403), `model_unavailable` (404 or a "model not found / decommissioned" error), `context_too_long`, `provider_unavailable` (5xx, timeouts, connection errors) or `bad_request`. Messages never include the key or the provider's raw answer.
- Short waits are absorbed: a 429 asking to wait 5 seconds or less is waited once, and `provider_unavailable` is retried twice with growing waits, but only before any text has been streamed.
- State is kept per provider: `auth_failed` stops its use until an administrator replaces the key; `quota_exhausted` until the next UTC day (or the provider's `retry-after`, if later); `model_unavailable` stops that model until an administrator re-enables it. Known limits per minute and per day are enforced by the gateway before calling, so the free tier is not hit in the first place.
- A **circuit breaker** per provider opens after 3 consecutive `provider_unavailable` failures and lets one trial call through after 60 seconds. It lives in process memory, like the rate limiter (ADR 0009).
- **No automatic fallback.** The `error` event says what happened, when to retry if known, and lists the other models currently available. The person picks one and retries.
- `context_too_long` is the one case handled without asking: the oldest history is dropped, the call is retried once, and a `notice` event says so.

## Consequences

- Data only goes to a provider the person or the administrator chose.
- Administrators see each provider's health (and why) through the admin API; visible alerts arrive with the panel in M7.
- With several gateway instances, each has its own breaker and per-minute counters; per-day limits are counted from the shared usage table.
