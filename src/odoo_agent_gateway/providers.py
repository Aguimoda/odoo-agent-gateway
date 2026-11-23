"""Provider registry: configuration, health and model choice (ADR 0015, 0017).

Used by the admin API (configure providers and models, see their health) and by the agent
service (resolve a model to a provider and its decrypted key, record how each call went).
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from odoo_agent_gateway.llm import ChatClient, CircuitBreaker, ProviderFailure, Target
from odoo_agent_gateway.odoo import InvalidRequest, RecordNotFound
from odoo_agent_gateway.provider_store import (
    Model,
    PostgresProviderStore,
    Provider,
    ProvidersUnavailable,
)
from odoo_agent_gateway.ratelimit import RateLimiter
from odoo_agent_gateway.secretbox import SecretBox, SecretError

logger = logging.getLogger(__name__)

LOOPBACK_NAMES = frozenset({"localhost"})
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_URL_LENGTH = 300


class ModelUnavailable(InvalidRequest):
    """The chosen model cannot be used right now. Carries the status for the caller."""

    code = "model_unavailable"

    def __init__(self, message: str, status: str, until: datetime | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.until = until


def normalize_base_url(url: str, local_hosts: frozenset[str]) -> str:
    """https only, except loopback hosts and the ones the server lists as local."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise InvalidRequest("Give the provider's API base URL (at most 300 characters).")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("https", "http") or not host:
        raise InvalidRequest("The provider URL must start with https:// and name a host.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise InvalidRequest("The provider URL cannot carry credentials, a query or a fragment.")
    if scheme == "http" and not _is_local(host, local_hosts):
        raise InvalidRequest(
            "Use https for providers on the internet; plain http is only for local models."
        )
    netloc = f"[{host}]" if ":" in host else host
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))


def _is_local(host: str, local_hosts: frozenset[str]) -> bool:
    if host in LOOPBACK_NAMES or host in local_hosts:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def next_utc_midnight(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def provider_status(
    provider: Provider, now: datetime, breaker: CircuitBreaker
) -> tuple[str, datetime | None]:
    if not provider.enabled:
        return "disabled", None
    if provider.api_key_encrypted is None:
        return "no_key", None
    if provider.auth_failed_at is not None:
        return "auth_failed", None
    if provider.exhausted_until is not None and provider.exhausted_until > now:
        return "exhausted", provider.exhausted_until
    if wait := breaker.open_for(provider.name):
        return "circuit_open", now + timedelta(seconds=round(wait))
    return "ok", None


def model_status(model: Model, provider: Provider, now: datetime, breaker: CircuitBreaker) -> str:
    if not model.enabled:
        return "disabled"
    if model.unavailable_at is not None:
        return "unavailable"
    return provider_status(provider, now, breaker)[0]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class ProviderRegistry:
    def __init__(
        self,
        store: PostgresProviderStore,
        box: SecretBox,
        chat: ChatClient,
        local_hosts: frozenset[str] = frozenset(),
        breaker: CircuitBreaker | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self._box = box
        self._chat = chat
        self._local_hosts = local_hosts
        self.breaker = breaker or CircuitBreaker()
        self._clock = clock
        self._per_minute: dict[tuple[str, int], RateLimiter] = {}

    # Views

    def _provider_view(self, provider: Provider, models: list[Model]) -> dict[str, Any]:
        now = self._clock()
        status, until = provider_status(provider, now, self.breaker)
        return {
            "id": provider.id,
            "name": provider.name,
            "base_url": provider.base_url,
            "enabled": provider.enabled,
            "key_set": provider.api_key_encrypted is not None,
            "key_updated_at": _iso(provider.key_updated_at),
            "requests_per_minute": provider.requests_per_minute,
            "requests_per_day": provider.requests_per_day,
            "status": status,
            "status_until": _iso(until),
            "last_error": provider.last_error_kind,
            "last_error_at": _iso(provider.last_error_at),
            "last_ok_at": _iso(provider.last_ok_at),
            "models": [
                {
                    "id": model.id,
                    "name": model.name,
                    "label": model.label,
                    "enabled": model.enabled,
                    "is_default": model.is_default,
                    "status": model_status(model, provider, now, self.breaker),
                }
                for model in models
                if model.provider_id == provider.id
            ],
        }

    async def overview(self) -> dict[str, Any]:
        models = await self.store.models()
        providers = await self.store.providers()
        return {"providers": [self._provider_view(p, models) for p in providers]}

    async def _view(self, provider_id: int) -> dict[str, Any]:
        provider = await self._provider(provider_id)
        return self._provider_view(provider, await self.store.models())

    async def _provider(self, provider_id: int) -> Provider:
        provider = await self.store.provider(provider_id)
        if provider is None:
            raise RecordNotFound("There is no provider with that id.")
        return provider

    async def _model(self, model_id: int) -> Model:
        model = await self.store.model(model_id)
        if model is None:
            raise RecordNotFound("There is no model with that id.")
        return model

    # Configuration (admin API)

    async def create_provider(self, data: dict[str, Any]) -> dict[str, Any]:
        name = (data.get("name") or "").strip().lower()
        if not NAME_PATTERN.match(name):
            raise InvalidRequest("Name: 1 to 40 lowercase letters, digits, - or _.")
        base_url = normalize_base_url(data.get("base_url", ""), self._local_hosts)
        values: dict[str, Any] = {"base_url": base_url, "enabled": data.get("enabled", True)}
        for limit in ("requests_per_minute", "requests_per_day"):
            values[limit] = data.get(limit)
        if api_key := (data.get("api_key") or "").strip():
            values["api_key_encrypted"] = self._box.encrypt(api_key, base_url)
            values["key_updated_at"] = self._clock()
        provider = await self.store.insert_provider(name, values)
        return self._provider_view(provider, [])

    async def update_provider(self, provider_id: int, data: dict[str, Any]) -> dict[str, Any]:
        provider = await self._provider(provider_id)
        values: dict[str, Any] = {}
        base_url = provider.base_url
        if data.get("base_url") is not None:
            base_url = normalize_base_url(data["base_url"], self._local_hosts)
            values["base_url"] = base_url
        api_key = (data.get("api_key") or "").strip()
        if base_url != provider.base_url and provider.api_key_encrypted and not api_key:
            raise InvalidRequest(
                "Changing the provider URL requires typing its API key again, so a stored key "
                "never goes to a different server."
            )
        if api_key:
            values["api_key_encrypted"] = self._box.encrypt(api_key, base_url)
            values["key_updated_at"] = self._clock()
            values["auth_failed_at"] = None  # a new key gets a new chance
        for name in ("enabled", "requests_per_minute", "requests_per_day"):
            if name in data:
                values[name] = data[name]
        await self.store.update_provider(provider_id, values)
        return await self._view(provider_id)

    async def delete_provider(self, provider_id: int) -> dict[str, Any]:
        if not await self.store.delete_provider(provider_id):
            raise RecordNotFound("There is no provider with that id.")
        return {"deleted": True, "provider_id": provider_id}

    async def add_model(self, provider_id: int, data: dict[str, Any]) -> dict[str, Any]:
        await self._provider(provider_id)
        name = (data.get("name") or "").strip()
        if not 1 <= len(name) <= 200:
            raise InvalidRequest("Give the model name as the provider writes it.")
        await self.store.insert_model(
            provider_id,
            name,
            (data.get("label") or "").strip() or None,
            data.get("enabled", True),
            bool(data.get("is_default")),
        )
        return await self._view(provider_id)

    async def update_model(self, model_id: int, data: dict[str, Any]) -> dict[str, Any]:
        model = await self._model(model_id)
        values = {k: data[k] for k in ("label", "enabled", "is_default") if k in data}
        if data.get("enabled"):
            values["unavailable_at"] = None  # re-enabling is how an admin clears it
        if values.get("is_default") is False and not model.is_default:
            values.pop("is_default")
        await self.store.update_model(model_id, values)
        return await self._view(model.provider_id)

    async def delete_model(self, model_id: int) -> dict[str, Any]:
        model = await self._model(model_id)
        await self.store.delete_model(model_id)
        return await self._view(model.provider_id)

    async def test_provider(self, provider_id: int) -> dict[str, Any]:
        """Ask the provider for its model list: checks URL and key, and helps fill models."""
        provider = await self._provider(provider_id)
        if provider.api_key_encrypted is None:
            raise InvalidRequest("Set the provider's API key first.")
        key = self._decrypt(provider)
        try:
            names = await self._chat.list_models(provider.base_url, key)
        except ProviderFailure as failure:
            await self.record_failure(provider, None, failure)
            return {"ok": False, "error": failure.kind, "message": failure.message}
        health: dict[str, Any] = {"last_ok_at": self._clock(), "auth_failed_at": None}
        await self.store.record_health(provider.id, health)
        return {"ok": True, "models": names[:500]}

    # Use (agent service)

    def _decrypt(self, provider: Provider) -> str:
        try:
            return self._box.decrypt(provider.api_key_encrypted, provider.base_url)
        except SecretError:
            logger.error("Provider %s: stored key cannot be decrypted (ADR 0015).", provider.name)
            raise ProvidersUnavailable(
                "This provider's stored key cannot be used; an administrator must set it again."
            ) from None

    async def available_models(self) -> list[dict[str, Any]]:
        now = self._clock()
        providers = {p.id: p for p in await self.store.providers()}
        result = []
        for model in await self.store.models():
            provider = providers[model.provider_id]
            if model_status(model, provider, now, self.breaker) == "ok":
                result.append(
                    {
                        "id": model.id,
                        "provider": provider.name,
                        "model": model.name,
                        "label": model.label or model.name,
                        "is_default": model.is_default,
                    }
                )
        return result

    async def resolve(self, model_id: int | None) -> Target:
        """The model to use, with its provider and decrypted key, or why it cannot be used."""
        if model_id is None:
            default = next((m for m in await self.store.models() if m.is_default), None)
            if default is None:
                raise ModelUnavailable(
                    "No default model is configured; choose one or ask an administrator.",
                    "no_default",
                )
            model = default
        else:
            model = await self._model(model_id)
        provider = await self._provider(model.provider_id)
        now = self._clock()
        status = model_status(model, provider, now, self.breaker)
        if status != "ok":
            until = provider_status(provider, now, self.breaker)[1]
            raise ModelUnavailable(f"This model is not available now ({status}).", status, until)
        return Target(
            model_id=model.id,
            provider_id=provider.id,
            provider=provider.name,
            model=model.name,
            label=model.label or model.name,
            base_url=provider.base_url,
            api_key=self._decrypt(provider),
        )

    async def acquire(self, target: Target) -> None:
        """Enforce the provider's known limits before calling it, and the circuit breaker."""
        provider = await self._provider(target.provider_id)
        if not self.breaker.allow(provider.name):
            raise ProviderFailure("provider_unavailable", self.breaker.open_for(provider.name))
        if provider.requests_per_day:
            today = self._clock().replace(hour=0, minute=0, second=0, microsecond=0)
            if await self.store.calls_since(provider.name, today) >= provider.requests_per_day:
                failure = ProviderFailure("quota_exhausted")
                await self.record_failure(provider, None, failure)
                raise failure
        if provider.requests_per_minute:
            key = (provider.name, provider.requests_per_minute)  # a new limit starts afresh
            limiter = self._per_minute.setdefault(key, RateLimiter(provider.requests_per_minute))
            if not limiter.allow(provider.name):
                raise ProviderFailure("rate_limited", retry_after=60.0)

    async def record_success(
        self,
        target: Target,
        login: str | None,
        latency_ms: int,
        tokens: tuple[int | None, int | None],
    ) -> None:
        self.breaker.success(target.provider)
        await self.store.record_health(target.provider_id, {"last_ok_at": self._clock()})
        await self.store.record_usage(
            provider=target.provider,
            model=target.model,
            login=login,
            outcome="ok",
            prompt_tokens=tokens[0],
            completion_tokens=tokens[1],
            latency_ms=latency_ms,
        )

    async def record_call_failure(
        self, target: Target, login: str | None, latency_ms: int, failure: ProviderFailure
    ) -> None:
        provider = await self.store.provider(target.provider_id)
        if provider is not None:
            await self.record_failure(provider, target.model_id, failure)
        await self.store.record_usage(
            provider=target.provider,
            model=target.model,
            login=login,
            outcome=failure.kind,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=latency_ms,
        )

    async def record_failure(
        self, provider: Provider, model_id: int | None, failure: ProviderFailure
    ) -> None:
        now = self._clock()
        health: dict[str, Any] = {"last_error_kind": failure.kind, "last_error_at": now}
        if failure.kind == "provider_unavailable":
            self.breaker.failure(provider.name)
        elif failure.kind == "auth_failed":
            health["auth_failed_at"] = now
            logger.warning(
                "Provider %s refused its API key: an admin must replace it.", provider.name
            )
        elif failure.kind == "quota_exhausted":
            until = next_utc_midnight(now)
            if failure.retry_after:
                until = max(until, now + timedelta(seconds=failure.retry_after))
            health["exhausted_until"] = until
            logger.warning("Provider %s daily quota used up until %s.", provider.name, until)
        elif failure.kind == "model_unavailable" and model_id is not None:
            await self.store.update_model(model_id, {"unavailable_at": now})
            logger.warning("Provider %s says model %s is unavailable.", provider.name, model_id)
        await self.store.record_health(provider.id, health)
