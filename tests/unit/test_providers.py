"""Provider rules that need no database: URLs, status and limits (ADR 0015, 0017)."""

from datetime import UTC, datetime, timedelta

import pytest

from odoo_agent_gateway.llm import CircuitBreaker
from odoo_agent_gateway.odoo import InvalidRequest
from odoo_agent_gateway.provider_store import Model, Provider
from odoo_agent_gateway.providers import (
    model_status,
    next_utc_midnight,
    normalize_base_url,
    provider_status,
)

NOW = datetime(2026, 11, 23, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://api.groq.com/openai/v1/", "https://api.groq.com/openai/v1"),
        ("HTTPS://API.Cerebras.ai/v1", "https://api.cerebras.ai/v1"),
        ("http://localhost:11434/v1", "http://localhost:11434/v1"),
        ("http://127.0.0.1:8080/v1", "http://127.0.0.1:8080/v1"),
        ("http://[::1]:8080/v1", "http://[::1]:8080/v1"),
        ("http://ollama:11434/v1", "http://ollama:11434/v1"),  # listed as local below
    ],
)
def test_accepted_urls(url, expected):
    assert normalize_base_url(url, frozenset({"ollama"})) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://api.groq.com/openai/v1",  # plain http to the internet
        "ftp://example.com",
        "https://user:pass@example.com/v1",  # credentials in the URL
        "https://example.com/v1?x=1",
        "https://example.com/v1#frag",
        "https:///v1",
        "not a url",
        "",
        "https://" + "a" * 300 + ".com",
    ],
)
def test_refused_urls(url):
    with pytest.raises(InvalidRequest):
        normalize_base_url(url, frozenset())


def provider(**changes) -> Provider:
    values = dict(
        id=1,
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_encrypted=b"x",
        key_updated_at=NOW,
        enabled=True,
        requests_per_minute=None,
        requests_per_day=None,
        auth_failed_at=None,
        exhausted_until=None,
        last_error_kind=None,
        last_error_at=None,
        last_ok_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return Provider(**values)


def model(**changes) -> Model:
    values = dict(
        id=10,
        provider_id=1,
        name="openai/gpt-oss-120b",
        label=None,
        enabled=True,
        is_default=True,
        unavailable_at=None,
        created_at=NOW,
    )
    values.update(changes)
    return Model(**values)


def breaker(open_provider: str | None = None) -> CircuitBreaker:
    result = CircuitBreaker(threshold=1, cooldown=60, clock=lambda: 0.0)
    if open_provider:
        result.failure(open_provider)
    return result


@pytest.mark.parametrize(
    "changes, status",
    [
        ({}, "ok"),
        ({"enabled": False}, "disabled"),
        ({"api_key_encrypted": None}, "no_key"),
        ({"auth_failed_at": NOW}, "auth_failed"),
        ({"exhausted_until": NOW + timedelta(hours=2)}, "exhausted"),
        ({"exhausted_until": NOW - timedelta(minutes=1)}, "ok"),  # quota is back
    ],
)
def test_provider_status(changes, status):
    assert provider_status(provider(**changes), NOW, breaker())[0] == status


def test_exhausted_says_until_when():
    until = NOW + timedelta(hours=2)
    assert provider_status(provider(exhausted_until=until), NOW, breaker()) == (
        "exhausted",
        until,
    )


def test_open_circuit_is_a_status_with_its_end():
    status, until = provider_status(provider(), NOW, breaker("groq"))
    assert status == "circuit_open" and until == NOW + timedelta(seconds=60)


def test_model_status_follows_its_provider():
    assert model_status(model(), provider(), NOW, breaker()) == "ok"
    assert model_status(model(enabled=False), provider(), NOW, breaker()) == "disabled"
    assert model_status(model(unavailable_at=NOW), provider(), NOW, breaker()) == "unavailable"
    assert model_status(model(), provider(auth_failed_at=NOW), NOW, breaker()) == "auth_failed"


def test_next_utc_midnight():
    assert next_utc_midnight(NOW) == datetime(2026, 11, 24, tzinfo=UTC)
