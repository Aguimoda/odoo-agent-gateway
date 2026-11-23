# 20. A normalized model catalog, a token budget before calling, and a final answer that always comes

Date: 2026-11-23. Status: accepted.

## Context

The first tests with real free providers (Groq, Gemini, OpenRouter, NVIDIA, Cloudflare) showed three things:

- Setting up models was guesswork: `/models` lists differ per provider (Groq gives context sizes, OpenRouter says which models take tools, Gemini and NVIDIA give only ids, Cloudflare has no `/models` on its OpenAI-compatible path at all), and the panel showed bare names.
- Free plans limit **tokens per minute** (Groq: 8,000). A multi-step question used about 10,000 tokens in under a minute, so the provider refused calls halfway through an answer, after steps and quota were already spent.
- When the agent ran out of steps, the last call ("answer with what you found", sent without tools but with the whole tool-call history) came back empty, as tool-call markup (`<tool_call>`), or as a stream error that the gateway took for "provider down". The person got nothing.

## Decision

**Catalog.** `GET /admin/providers/{id}/catalog` asks the provider for its models and returns one shape for all: `id`, `owned_by`, `active`, `context_window`, `max_output_tokens`, `tools` (`true`, `false` or `null` when the provider does not say), `kind` (`chat`, `embedding`, `audio`, `image`, `moderation`, `other`) and `added`. Fields come from what each provider publishes; `kind` falls back to well-known name patterns. Cloudflare Workers AI, which has no `/models`, is read from its own model search API on the same account, with the same key. The result is cached in memory for 10 minutes per provider. Only administrators can ask (ADR 0015) and keys never appear in it. "Test connection" uses the same path, so it works for Cloudflare too.

**Token budget.** A provider can have `tokens_per_minute`. Before each call the gateway adds the tokens that provider used in the last 60 seconds (from `llm_usage`) and an estimate of the request (characters / 4). If it does not fit, it waits when the wait is short (5 seconds or less, like `retry-after`) and otherwise fails with `rate_limited` and the computed wait, **without calling the provider**. A request that would not fit even in an empty minute is let through, so a low limit never blocks a provider forever. Usage is asked for in streams (`stream_options.include_usage`); when a provider still does not report tokens, the estimate is recorded instead.

**Final answer.** The last call no longer carries tool calls: what the tools returned is passed as plain text in one message, with no tools offered, so the model cannot ask for one. If the reply is empty or only tool-call markup, the person gets an honest message in their language (from `Accept-Language`) saying the assistant could not finish, with the tools it used shown as usual.

**Provider errors.** An `error` event inside a stream is classified like an HTTP error, from its status or code, instead of always meaning "provider down". The provider's short error code (never its text) is kept in `llm_usage.error_code` for diagnosis, and the full reason goes only to the server log, never to people or the database.

## Consequences

- Administrators pick models with the information that matters (tools, context size) and see Cloudflare's models like any other provider's.
- Free plans are hit less often, and when they would be, the person learns it before steps are wasted. With several gateway instances the per-minute count is shared, because it is read from the database.
- The estimate is rough (characters / 4); it only has to be good enough to stay under a limit, not to bill.
- Every turn ends with an answer or a clear explanation; nothing new reaches the provider (the same tool results, as text).
