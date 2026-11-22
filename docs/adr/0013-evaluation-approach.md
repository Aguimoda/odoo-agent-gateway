# 13. Measure retrieval in CI; evaluate real agents with any OpenAI-compatible provider

Date: 2026-11-23. Status: accepted.

## Context

M1 to M4 proved permissions with tests. Quality is a different question: does retrieval rank the right passage, does it stay quiet when there is no answer, and does a real agent use the tools well? Some of this needs no language model. Agent behaviour does, and a hosted model needs an API key, costs money or has rate limits, and sends text to a third party.

## Decision

- **Retrieval evaluation runs in CI**, against the real index, with a labelled set of questions in Spanish and English that includes unanswerable ones. It reports hit@1, hit@3, mean reciprocal rank and the noise returned for unanswerable questions, saves results under `evals/results/`, and fails below agreed minimums.
- **The relevance threshold is calibrated from that data**, not guessed, and documented with the numbers that justified it.
- **The agent evaluation talks to any OpenAI-compatible Chat Completions API** (Groq, Cerebras, a local model) configured by `AGENT_EVAL_BASE_URL`, `AGENT_EVAL_MODEL` and `AGENT_EVAL_API_KEY`. No provider SDK is added; the key is read from the environment only, never written to files, logs or results.
- The agent uses the gateway over MCP HTTP as a demo user, exactly like a real client, and is scored on: right first tool, cited source, no secret of another user in the answer, and no write proposed because of hostile text.
- **The agent evaluation runs manually**, because free tiers are rate-limited and results vary between runs. Its results are committed with the model name and date. Its harness is tested in CI with a scripted fake provider.

## Consequences

- Retrieval regressions are caught on every push.
- Agent results depend on the model chosen; an open model on a free tier will score lower than the best paid models, and the report says which model produced which numbers.
- Text sent to the provider is the fictional demo data only.
