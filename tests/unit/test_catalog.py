"""The model catalog: every provider's list in one shape (ADR 0020)."""

import pytest

from odoo_agent_gateway.catalog import (
    cloudflare_search_url,
    model_kind,
    normalize_cloudflare,
    normalize_models,
)

GROQ = {
    "object": "list",
    "data": [
        {
            "id": "openai/gpt-oss-120b",
            "object": "model",
            "owned_by": "OpenAI",
            "active": True,
            "context_window": 131072,
            "max_completion_tokens": 65536,
        },
        {"id": "whisper-large-v3", "owned_by": "OpenAI", "active": True, "context_window": 448},
    ],
}

OPENROUTER = {
    "data": [
        {
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "context_length": 262144,
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "top_provider": {"max_completion_tokens": 32768},
            "supported_parameters": ["max_tokens", "tools", "tool_choice"],
        },
        {
            "id": "liquid/lfm-3-1.7b:free",
            "context_length": 32768,
            "architecture": {"output_modalities": ["text"]},
            "supported_parameters": ["max_tokens"],
        },
        {
            "id": "google/some-image-model",
            "architecture": {"output_modalities": ["image"]},
            "supported_parameters": [],
        },
    ]
}

GEMINI = {
    "object": "list",
    "data": [
        {"id": "models/gemini-3.5-flash-lite", "object": "model", "owned_by": "google"},
        {"id": "models/gemini-embedding-2", "object": "model", "owned_by": "google"},
        {"id": "models/gemini-3.8-flash-tts", "object": "model", "owned_by": "google"},
    ],
}

CLOUDFLARE = {
    "success": True,
    "result": [
        {
            "name": "@cf/openai/gpt-oss-120b",
            "task": {"name": "Text Generation"},
            "properties": [
                {"property_id": "context_window", "value": "128000"},
                {"property_id": "function_calling", "value": "true"},
            ],
        },
        {
            "name": "@cf/baai/bge-m3",
            "task": {"name": "Text Embeddings"},
            "properties": [],
        },
        {
            "name": "@cf/meta/llama-3.1-8b-instruct",
            "task": {"name": "Text Generation"},
            "properties": [{"property_id": "context_window", "value": "not a number"}],
        },
    ],
}


def by_id(models):
    return {m["id"]: m for m in models}


def test_groq_gives_context_and_output_sizes():
    models = by_id(normalize_models(GROQ))
    gpt = models["openai/gpt-oss-120b"]
    assert gpt == {
        "id": "openai/gpt-oss-120b",
        "owned_by": "OpenAI",
        "active": True,
        "context_window": 131072,
        "max_output_tokens": 65536,
        "tools": None,
        "kind": "chat",
    }
    assert models["whisper-large-v3"]["kind"] == "audio"


def test_openrouter_says_which_models_take_tools():
    models = by_id(normalize_models(OPENROUTER))
    nemotron = models["nvidia/nemotron-3-ultra-550b-a55b:free"]
    assert nemotron["tools"] is True
    assert nemotron["context_window"] == 262144
    assert nemotron["max_output_tokens"] == 32768
    assert models["liquid/lfm-3-1.7b:free"]["tools"] is False
    assert models["google/some-image-model"]["kind"] == "image"


def test_gemini_gives_ids_only_and_kinds_come_from_the_name():
    models = by_id(normalize_models(GEMINI))
    assert models["models/gemini-3.5-flash-lite"]["kind"] == "chat"
    assert models["models/gemini-3.5-flash-lite"]["context_window"] is None
    assert models["models/gemini-embedding-2"]["kind"] == "embedding"
    assert models["models/gemini-3.8-flash-tts"]["kind"] == "audio"


def test_cloudflare_search_is_read_like_the_others():
    models = by_id(normalize_cloudflare(CLOUDFLARE))
    gpt = models["@cf/openai/gpt-oss-120b"]
    assert gpt["tools"] is True and gpt["context_window"] == 128000 and gpt["kind"] == "chat"
    assert models["@cf/baai/bge-m3"]["kind"] == "embedding"
    llama = models["@cf/meta/llama-3.1-8b-instruct"]
    assert llama["tools"] is None and llama["context_window"] is None


@pytest.mark.parametrize(
    "name, kind",
    [
        ("openai/gpt-oss-120b", "chat"),
        ("nvidia/llama-3.1-nemotron-safety-guard-8b-v3", "moderation"),
        ("meta-llama/llama-prompt-guard-2-86m", "moderation"),
        ("nvidia/nv-embedqa-mistral-7b-v2", "embedding"),
        ("canopylabs/orpheus-v1-english", "audio"),
        ("models/gemini-3.1-flash-image", "image"),
        ("models/aqa", "other"),
        ("fastino/gliner2-pii", "moderation"),
    ],
)
def test_kind_from_name(name, kind):
    assert model_kind(name) == kind


@pytest.mark.parametrize(
    "base_url, search",
    [
        (
            "https://api.cloudflare.com/client/v4/accounts/a36775ed720079f8fed7c763b489bab5/ai/v1",
            "https://api.cloudflare.com/client/v4/accounts/a36775ed720079f8fed7c763b489bab5/ai/models/search",
        ),
        ("https://api.groq.com/openai/v1", None),
        ("https://evil.example/client/v4/accounts/a36775ed720079f8fed7c763b489bab5/ai/v1", None),
    ],
)
def test_cloudflare_search_only_on_cloudflare_itself(base_url, search):
    assert cloudflare_search_url(base_url) == search


def test_odd_entries_are_skipped_not_fatal():
    assert normalize_models({"data": [None, {"no_id": 1}, {"id": ""}, {"id": "ok"}]}) == [
        {
            "id": "ok",
            "owned_by": None,
            "active": None,
            "context_window": None,
            "max_output_tokens": None,
            "tools": None,
            "kind": "chat",
        }
    ]
    assert normalize_models("not json") == []
