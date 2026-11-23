"""Token budget and error codes against the gateway's real PostgreSQL (ADR 0020)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from odoo_agent_gateway.llm import ChatClient, ProviderFailure, Target
from odoo_agent_gateway.provider_store import PostgresProviderStore
from odoo_agent_gateway.providers import ProviderRegistry
from odoo_agent_gateway.secretbox import SecretBox

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

KEYS_FILE = Path(__file__).resolve().parents[2] / ".env.demo-keys"


def missing(reason: str):
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def database_url() -> str:
    if url := os.environ.get("GATEWAY_DATABASE_URL"):
        return url
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("GATEWAY_DATABASE_URL="):
                return line.split("=", 1)[1]
    missing("No gateway database: run scripts/demo/setup_demo.py first.")


@pytest.fixture
async def store():
    providers = PostgresProviderStore(database_url())
    await providers.start()
    yield providers
    await providers.close()


@pytest.fixture
async def provider(store):
    """A throwaway provider with a tokens-per-minute limit, removed afterwards."""
    name = f"budget-{uuid.uuid4().hex[:8]}"
    created = await store.insert_provider(
        name, {"base_url": "https://budget.test/v1", "enabled": True, "tokens_per_minute": 8000}
    )
    yield created
    await store.delete_provider(created.id)
    # Leave no test rows in the usage the admin panel shows.
    await store._ready().execute("delete from llm_usage where provider = $1", name)


def target(provider) -> Target:
    return Target(
        model_id=0,
        provider_id=provider.id,
        provider=provider.name,
        model="m",
        label="m",
        base_url=provider.base_url,
        api_key="fixture-not-a-real-credential",
    )


def registry(store, sleeps=None) -> ProviderRegistry:
    async def sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    return ProviderRegistry(store, SecretBox([os.urandom(32)]), ChatClient(None), sleep=sleep)


async def use(store, provider, prompt, completion=0, seconds_ago=0):
    await store.record_usage(
        provider=provider.name,
        model="m",
        login="ana",
        outcome="ok",
        prompt_tokens=prompt,
        completion_tokens=completion,
        latency_ms=100,
    )
    if seconds_ago:
        await store._ready().execute(
            "update llm_usage set at = now() - make_interval(secs => $2) "
            "where provider = $1 and at > now() - interval '5 seconds'",
            provider.name,
            seconds_ago,
        )


async def test_tokens_since_sums_the_last_minute_only(store, provider):
    await use(store, provider, 3000, 500, seconds_ago=120)  # outside the window
    await use(store, provider, 2000, 1000)
    used, oldest = await store.tokens_since(
        provider.name, datetime.now(UTC) - timedelta(seconds=60)
    )
    assert used == 3000
    assert oldest is not None


async def test_a_call_that_fits_goes_through(store, provider):
    await use(store, provider, 2000)
    await registry(store).acquire(target(provider), estimate=3000)


async def test_a_call_that_does_not_fit_is_refused_before_calling(store, provider):
    """Scenario: límite de tokens por minuto."""
    await use(store, provider, 7500, seconds_ago=10)
    with pytest.raises(ProviderFailure) as raised:
        await registry(store).acquire(target(provider), estimate=3000)
    assert raised.value.kind == "rate_limited"
    assert raised.value.code == "token_budget"
    assert 45 <= raised.value.retry_after <= 51


async def test_a_short_wait_is_absorbed(store, provider):
    await use(store, provider, 7500, seconds_ago=57)
    sleeps = []
    with pytest.raises(ProviderFailure):  # the usage is still there after the fake sleep
        await registry(store, sleeps).acquire(target(provider), estimate=3000)
    assert len(sleeps) == 1 and sleeps[0] <= 5


async def test_the_error_code_is_stored(store, provider):
    await store.record_usage(
        provider=provider.name,
        model="m",
        login="ana",
        outcome="bad_request",
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=10,
        error_code="tool_use_failed",
    )
    code = await store._ready().fetchval(
        "select error_code from llm_usage where provider = $1", provider.name
    )
    assert code == "tool_use_failed"
