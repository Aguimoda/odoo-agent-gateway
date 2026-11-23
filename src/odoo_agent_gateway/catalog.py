"""The model catalog: what each provider offers, in one shape (ADR 0020).

Providers publish their model lists differently: Groq gives context sizes, OpenRouter says
which models take tools, Gemini and NVIDIA give only ids, and Cloudflare Workers AI has no
`/models` on its OpenAI-compatible path but a model search API on the same account. Each
field is filled only from what the provider says; `kind` falls back to well-known names.
"""

from __future__ import annotations

import re
from typing import Any

KINDS = ("chat", "embedding", "audio", "image", "moderation", "other")

# Order matters: the first pattern that matches wins.
_NAME_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("moderation", ("guard", "safety", "moderation", "content-safety", "-pii", "/pii")),
    ("embedding", ("embed", "bge-", "/e5-", "retriever", "nvclip", "rerank")),
    (
        "audio",
        ("whisper", "tts", "orpheus", "transcribe", "native-audio", "speech", "lyria", "-live"),
    ),
    ("image", ("image", "flux", "stable-diffusion", "dall-e", "imagen", "veo", "video", "banana")),
    ("other", ("/aqa", "robotics", "computer-use", "deep-research", "genie")),
)

_CLOUDFLARE_TASKS = {
    "text generation": "chat",
    "text embeddings": "embedding",
    "automatic speech recognition": "audio",
    "text-to-speech": "audio",
    "text-to-image": "image",
    "image-to-text": "chat",
}

_CLOUDFLARE_BASE = re.compile(
    r"^https://api\.cloudflare\.com/client/v4/accounts/([0-9a-f]{32})/ai/v1$"
)


def model_kind(name: str) -> str:
    lowered = name.lower()
    for kind, needles in _NAME_KINDS:
        if any(needle in lowered for needle in needles):
            return kind
    return "chat"


def _int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _entry(
    model_id: str,
    *,
    owned_by: Any = None,
    active: Any = None,
    context_window: Any = None,
    max_output_tokens: Any = None,
    tools: bool | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    return {
        "id": model_id,
        "owned_by": owned_by if isinstance(owned_by, str) else None,
        "active": active if isinstance(active, bool) else None,
        "context_window": _int(context_window),
        "max_output_tokens": _int(max_output_tokens),
        "tools": tools,
        "kind": kind or model_kind(model_id),
    }


def normalize_models(payload: Any) -> list[dict[str, Any]]:
    """An OpenAI-style `/models` answer (Groq, OpenRouter, Gemini, NVIDIA, Ollama…)."""
    data = payload.get("data") if isinstance(payload, dict) else None
    result = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        parameters = item.get("supported_parameters")
        tools = ("tools" in parameters) if isinstance(parameters, list) else None
        outputs = (item.get("architecture") or {}).get("output_modalities")
        kind = None
        if isinstance(outputs, list) and outputs and "text" not in outputs:
            kind = "image" if "image" in outputs else "audio" if "audio" in outputs else "other"
        top = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
        result.append(
            _entry(
                item["id"],
                owned_by=item.get("owned_by"),
                active=item.get("active"),
                context_window=item.get("context_window") or item.get("context_length"),
                max_output_tokens=item.get("max_completion_tokens")
                or top.get("max_completion_tokens"),
                tools=tools,
                kind=kind,
            )
        )
    return result


def cloudflare_search_url(base_url: str) -> str | None:
    """Cloudflare's model search on the same account, only for Cloudflare's own API host."""
    if not _CLOUDFLARE_BASE.match(base_url):
        return None
    return base_url[: -len("/ai/v1")] + "/ai/models/search"


def normalize_cloudflare(payload: Any) -> list[dict[str, Any]]:
    """Cloudflare Workers AI's model search answer."""
    data = payload.get("result") if isinstance(payload, dict) else None
    result = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]:
            continue
        properties = {
            p.get("property_id"): p.get("value")
            for p in item.get("properties") or []
            if isinstance(p, dict)
        }
        task = ((item.get("task") or {}).get("name") or "").lower()
        calling = str(properties.get("function_calling", "")).lower()
        result.append(
            _entry(
                item["name"],
                context_window=properties.get("context_window"),
                tools=True if calling == "true" else None,
                kind=_CLOUDFLARE_TASKS.get(task)
                or (model_kind(item["name"]) if not task else "other"),
            )
        )
    return result
