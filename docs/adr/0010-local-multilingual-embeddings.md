# 10. Local multilingual embeddings, behind a replaceable interface

Date: 2026-11-22. Status: accepted.

## Context

Retrieval needs text embeddings. Options: a hosted API (OpenAI, Azure OpenAI, Voyage), or a model running inside the gateway. A hosted API sends company text to a third party, costs money per call and needs another secret. The demo company and its users write in Spanish and English.

A first check with `fastembed` 0.9 (ONNX runtime, no PyTorch) and `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: three Spanish questions each matched the right English passage, embedding took milliseconds, and the model is 220 MB under the Apache 2.0 licence.

## Decision

- Use `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions) through `fastembed`, running locally.
- Hide it behind an `Embedder` interface (`embed(texts) -> vectors`, `dimension`), so a hosted provider can replace it without touching retrieval code.
- Keep the model cache in a project folder (`GATEWAY_MODEL_CACHE`, default `.cache/models`, git-ignored), not the system temp folder.
- Vectors are L2-normalised and compared by cosine distance.

## Consequences

- No company text leaves the machine for retrieval; no API cost or key.
- First start downloads the model (about 220 MB) from Hugging Face; CI caches it.
- Quality is below the best hosted models. Measured in M3 with a small retrieval set and in M5 more broadly; switching is a configuration and re-index, not a rewrite.
- The vector column is fixed at 384 dimensions. Changing models means a migration and a full re-index.
