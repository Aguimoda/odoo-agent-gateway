"""Storage for language-model providers, models, usage and agent settings (ADR 0015, 0017)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from odoo_agent_gateway.migrations import apply_migrations
from odoo_agent_gateway.odoo import OdooError


class ProvidersUnavailable(OdooError):
    code = "providers_unavailable"


class DuplicateName(OdooError):
    code = "conflict"


@dataclass(frozen=True)
class Provider:
    id: int
    name: str
    base_url: str
    api_key_encrypted: bytes | None
    key_updated_at: datetime | None
    enabled: bool
    requests_per_minute: int | None
    requests_per_day: int | None
    auth_failed_at: datetime | None
    exhausted_until: datetime | None
    last_error_kind: str | None
    last_error_at: datetime | None
    last_ok_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def __repr__(self) -> str:  # never print the (encrypted) key
        return f"Provider(id={self.id}, name={self.name!r}, base_url={self.base_url!r})"


@dataclass(frozen=True)
class Model:
    id: int
    provider_id: int
    name: str
    label: str | None
    enabled: bool
    is_default: bool
    unavailable_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class AgentSettings:
    instructions: str = ""
    retention_days: int = 30
    disabled_tools: tuple[str, ...] = ()
    max_steps: int = 6
    updated_at: datetime | None = None
    updated_by: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "instructions": self.instructions,
            "retention_days": self.retention_days,
            "disabled_tools": list(self.disabled_tools),
            "max_steps": self.max_steps,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by,
        }


_PROVIDER_COLUMNS = (
    "id, name, base_url, api_key_encrypted, key_updated_at, enabled, requests_per_minute, "
    "requests_per_day, auth_failed_at, exhausted_until, last_error_kind, last_error_at, "
    "last_ok_at, created_at, updated_at"
)
_MODEL_COLUMNS = "id, provider_id, name, label, enabled, is_default, unavailable_at, created_at"

# Columns callers may set. Anything else is a programming error, never user input.
_PROVIDER_WRITABLE = {
    "base_url",
    "api_key_encrypted",
    "key_updated_at",
    "enabled",
    "requests_per_minute",
    "requests_per_day",
    "auth_failed_at",
    "exhausted_until",
    "last_error_kind",
    "last_error_at",
    "last_ok_at",
}
_MODEL_WRITABLE = {"label", "enabled", "is_default", "unavailable_at"}
_SETTINGS_WRITABLE = {"instructions", "retention_days", "disabled_tools", "max_steps"}


def _assignments(values: dict[str, Any], allowed: set[str], start: int) -> tuple[str, list]:
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Not writable: {sorted(unknown)}")
    names = sorted(values)
    sql = ", ".join(f"{name} = ${start + i}" for i, name in enumerate(names))
    return sql, [values[name] for name in names]


class PostgresProviderStore:
    def __init__(self, dsn: str, timeout: float = 10.0) -> None:
        self._dsn = dsn
        self._timeout = timeout
        self._pool: asyncpg.Pool | None = None

    def __repr__(self) -> str:
        return "PostgresProviderStore()"  # the DSN contains a password

    async def start(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=5, timeout=self._timeout
            )
            async with self._pool.acquire() as connection:
                await apply_migrations(connection)
        except (OSError, asyncpg.PostgresError, TimeoutError) as error:
            raise ProvidersUnavailable("The providers database could not be reached.") from error

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _ready(self) -> asyncpg.Pool:
        if self._pool is None:
            raise ProvidersUnavailable("The providers store is not started.")
        return self._pool

    # Providers

    async def providers(self) -> list[Provider]:
        rows = await self._ready().fetch(
            f"select {_PROVIDER_COLUMNS} from llm_providers order by name"
        )
        return [Provider(**dict(row)) for row in rows]

    async def provider(self, provider_id: int) -> Provider | None:
        row = await self._ready().fetchrow(
            f"select {_PROVIDER_COLUMNS} from llm_providers where id = $1", provider_id
        )
        return Provider(**dict(row)) if row else None

    async def insert_provider(self, name: str, values: dict[str, Any]) -> Provider:
        names = ["name", *sorted(values)]
        unknown = set(values) - _PROVIDER_WRITABLE
        if unknown:
            raise ValueError(f"Not writable: {sorted(unknown)}")
        placeholders = ", ".join(f"${i + 1}" for i in range(len(names)))
        try:
            row = await self._ready().fetchrow(
                f"insert into llm_providers ({', '.join(names)}) values ({placeholders}) "
                f"returning {_PROVIDER_COLUMNS}",
                name,
                *(values[key] for key in sorted(values)),
            )
        except asyncpg.UniqueViolationError:
            raise DuplicateName("A provider with that name already exists.") from None
        return Provider(**dict(row))

    async def update_provider(self, provider_id: int, values: dict[str, Any]) -> Provider | None:
        if not values:
            return await self.provider(provider_id)
        sql, params = _assignments(values, _PROVIDER_WRITABLE, 2)
        row = await self._ready().fetchrow(
            f"update llm_providers set {sql}, updated_at = now() where id = $1 "
            f"returning {_PROVIDER_COLUMNS}",
            provider_id,
            *params,
        )
        return Provider(**dict(row)) if row else None

    async def record_health(self, provider_id: int, values: dict[str, Any]) -> None:
        """Health changes do not count as configuration changes: updated_at stays."""
        sql, params = _assignments(values, _PROVIDER_WRITABLE, 2)
        await self._ready().execute(
            f"update llm_providers set {sql} where id = $1", provider_id, *params
        )

    async def delete_provider(self, provider_id: int) -> bool:
        result = await self._ready().execute("delete from llm_providers where id = $1", provider_id)
        return result.endswith(" 1")

    # Models

    async def models(self) -> list[Model]:
        rows = await self._ready().fetch(
            f"select {_MODEL_COLUMNS} from llm_models order by provider_id, name"
        )
        return [Model(**dict(row)) for row in rows]

    async def model(self, model_id: int) -> Model | None:
        row = await self._ready().fetchrow(
            f"select {_MODEL_COLUMNS} from llm_models where id = $1", model_id
        )
        return Model(**dict(row)) if row else None

    async def insert_model(
        self, provider_id: int, name: str, label: str | None, enabled: bool, is_default: bool
    ) -> Model:
        async with self._ready().acquire() as connection, connection.transaction():
            if is_default:
                await connection.execute("update llm_models set is_default = false")
            try:
                row = await connection.fetchrow(
                    "insert into llm_models (provider_id, name, label, enabled, is_default) "
                    f"values ($1, $2, $3, $4, $5) returning {_MODEL_COLUMNS}",
                    provider_id,
                    name,
                    label,
                    enabled,
                    is_default,
                )
            except asyncpg.UniqueViolationError:
                raise DuplicateName("That provider already has a model with that name.") from None
        return Model(**dict(row))

    async def update_model(self, model_id: int, values: dict[str, Any]) -> Model | None:
        if not values:
            return await self.model(model_id)
        sql, params = _assignments(values, _MODEL_WRITABLE, 2)
        async with self._ready().acquire() as connection, connection.transaction():
            if values.get("is_default"):
                await connection.execute(
                    "update llm_models set is_default = false where id <> $1", model_id
                )
            row = await connection.fetchrow(
                f"update llm_models set {sql} where id = $1 returning {_MODEL_COLUMNS}",
                model_id,
                *params,
            )
        return Model(**dict(row)) if row else None

    async def delete_model(self, model_id: int) -> bool:
        result = await self._ready().execute("delete from llm_models where id = $1", model_id)
        return result.endswith(" 1")

    # Usage

    async def record_usage(
        self,
        *,
        provider: str,
        model: str,
        login: str | None,
        outcome: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: int,
    ) -> None:
        await self._ready().execute(
            "insert into llm_usage (provider, model, login, outcome, prompt_tokens, "
            "completion_tokens, latency_ms) values ($1, $2, $3, $4, $5, $6, $7)",
            provider,
            model,
            login,
            outcome,
            prompt_tokens,
            completion_tokens,
            latency_ms,
        )

    async def calls_since(self, provider: str, since: datetime) -> int:
        return await self._ready().fetchval(
            "select count(*) from llm_usage where provider = $1 and at >= $2", provider, since
        )

    async def usage_summary(self, since: datetime) -> list[dict[str, Any]]:
        rows = await self._ready().fetch(
            """
            select provider, model, count(*) as calls,
                   count(*) filter (where outcome = 'ok') as ok,
                   coalesce(sum(prompt_tokens), 0) as prompt_tokens,
                   coalesce(sum(completion_tokens), 0) as completion_tokens,
                   round(percentile_cont(0.5) within group (order by latency_ms)) as p50_ms,
                   round(percentile_cont(0.95) within group (order by latency_ms)) as p95_ms
            from llm_usage where at >= $1
            group by provider, model order by calls desc, provider, model
            """,
            since,
        )
        errors = await self._ready().fetch(
            """
            select provider, model, outcome, count(*) as n from llm_usage
            where at >= $1 and outcome <> 'ok' group by provider, model, outcome
            """,
            since,
        )
        by_key: dict[tuple[str, str], dict[str, int]] = {}
        for row in errors:
            by_key.setdefault((row["provider"], row["model"]), {})[row["outcome"]] = row["n"]
        return [
            {
                **{key: row[key] for key in ("provider", "model", "calls", "ok")},
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
                "p50_ms": int(row["p50_ms"]),
                "p95_ms": int(row["p95_ms"]),
                "errors": by_key.get((row["provider"], row["model"]), {}),
            }
            for row in rows
        ]

    # Settings

    async def settings(self) -> AgentSettings:
        row = await self._ready().fetchrow(
            "select instructions, retention_days, disabled_tools, max_steps, updated_at, "
            "updated_by from agent_settings where id"
        )
        values = dict(row)
        values["disabled_tools"] = tuple(values["disabled_tools"])
        return AgentSettings(**values)

    async def update_settings(self, values: dict[str, Any], updated_by: str) -> AgentSettings:
        sql, params = _assignments(values, _SETTINGS_WRITABLE, 2)
        prefix = f"{sql}, " if sql else ""
        await self._ready().execute(
            f"update agent_settings set {prefix}updated_at = now(), updated_by = $1 where id",
            updated_by,
            *params,
        )
        return await self.settings()
