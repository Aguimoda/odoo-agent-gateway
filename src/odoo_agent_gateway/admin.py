"""The admin API (ADR 0015): providers, models, agent settings and usage.

Odoo decides who is an administrator: the caller must belong to the configured group,
asked of Odoo as the caller. Every call takes the shared Gateway path (rate limit,
credentials, fail-closed audit). Provider API keys are write-only and never audited.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from odoo_agent_gateway.gateway import Gateway
from odoo_agent_gateway.http_api import call_through_gateway
from odoo_agent_gateway.odoo import AccessDenied, InvalidRequest, OdooSession
from odoo_agent_gateway.provider_store import ProvidersUnavailable
from odoo_agent_gateway.providers import ProviderRegistry

SECRET_FIELDS = ("api_key",)


class ProviderIn(BaseModel):
    name: str = Field(max_length=40)
    base_url: str = Field(max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    requests_per_minute: int | None = Field(default=None, gt=0)
    requests_per_day: int | None = Field(default=None, gt=0)
    tokens_per_minute: int | None = Field(default=None, gt=0)


class ProviderPatch(BaseModel):
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    requests_per_minute: int | None = Field(default=None, gt=0)
    requests_per_day: int | None = Field(default=None, gt=0)
    tokens_per_minute: int | None = Field(default=None, gt=0)


class ModelIn(BaseModel):
    name: str = Field(max_length=200)
    label: str | None = Field(default=None, max_length=100)
    enabled: bool = True
    is_default: bool = False


class ModelPatch(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    is_default: bool | None = None


class SettingsPatch(BaseModel):
    instructions: str | None = Field(default=None, max_length=4000)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    disabled_tools: list[str] | None = Field(default=None, max_length=50)
    max_steps: int | None = Field(default=None, ge=1, le=20)


def audit_arguments(data: dict[str, Any]) -> dict[str, Any]:
    """What the audit log may keep of a request: secrets replaced by a marker."""
    return {
        key: ("***" if key in SECRET_FIELDS and value else value) for key, value in data.items()
    }


async def require_admin(session: OdooSession, group: str) -> None:
    if not await session.call("res.users", "has_group", [[session.uid], group]):
        raise AccessDenied("Only administrators of the assistant can do this.")


def build_admin_router(
    gateway: Gateway,
    registry: ProviderRegistry | None,
    admin_group: str,
    allowed_hosts: tuple[str, ...],
    tool_names: Callable[[], Awaitable[list[str]]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    async def respond(
        request: Request,
        tool: str,
        arguments: dict[str, Any],
        action: Callable[[ProviderRegistry, OdooSession], Awaitable[Any]],
    ) -> Any:
        async def run(session: OdooSession) -> Any:
            await require_admin(session, admin_group)
            if registry is None:
                raise ProvidersUnavailable(
                    "Providers are not configured on this gateway: set GATEWAY_SECRET_KEYS."
                )
            return await action(registry, session)

        return await call_through_gateway(
            gateway, request, allowed_hosts, tool, audit_arguments(arguments), run
        )

    @router.get("/providers")
    async def list_providers(request: Request) -> Any:
        """Providers with their models and health. Keys are never returned."""
        return await respond(request, "admin.providers", {}, lambda r, s: r.overview())

    @router.post("/providers")
    async def create_provider(request: Request, body: ProviderIn) -> Any:
        data = body.model_dump()
        return await respond(
            request, "admin.create_provider", data, lambda r, s: r.create_provider(data)
        )

    @router.patch("/providers/{provider_id}")
    async def update_provider(provider_id: int, request: Request, body: ProviderPatch) -> Any:
        data = body.model_dump(exclude_unset=True)
        return await respond(
            request,
            "admin.update_provider",
            {"provider_id": provider_id, **data},
            lambda r, s: r.update_provider(provider_id, data),
        )

    @router.delete("/providers/{provider_id}")
    async def delete_provider(provider_id: int, request: Request) -> Any:
        return await respond(
            request,
            "admin.delete_provider",
            {"provider_id": provider_id},
            lambda r, s: r.delete_provider(provider_id),
        )

    @router.post("/providers/{provider_id}/test")
    async def test_provider(provider_id: int, request: Request) -> Any:
        """Check URL and key by asking the provider for its models."""
        return await respond(
            request,
            "admin.test_provider",
            {"provider_id": provider_id},
            lambda r, s: r.test_provider(provider_id),
        )

    @router.post("/providers/{provider_id}/models")
    async def add_model(provider_id: int, request: Request, body: ModelIn) -> Any:
        data = body.model_dump()
        return await respond(
            request,
            "admin.add_model",
            {"provider_id": provider_id, **data},
            lambda r, s: r.add_model(provider_id, data),
        )

    @router.patch("/models/{model_id}")
    async def update_model(model_id: int, request: Request, body: ModelPatch) -> Any:
        data = body.model_dump(exclude_unset=True)
        return await respond(
            request,
            "admin.update_model",
            {"model_id": model_id, **data},
            lambda r, s: r.update_model(model_id, data),
        )

    @router.delete("/models/{model_id}")
    async def delete_model(model_id: int, request: Request) -> Any:
        return await respond(
            request,
            "admin.delete_model",
            {"model_id": model_id},
            lambda r, s: r.delete_model(model_id),
        )

    @router.get("/settings")
    async def get_settings(request: Request) -> Any:
        async def action(r: ProviderRegistry, s: OdooSession) -> Any:
            tools = await tool_names() if tool_names else []
            return {**(await r.store.settings()).public(), "tools": tools}

        return await respond(request, "admin.settings", {}, action)

    @router.patch("/settings")
    async def update_settings(request: Request, body: SettingsPatch) -> Any:
        data = body.model_dump(exclude_unset=True, exclude_none=True)

        async def action(r: ProviderRegistry, s: OdooSession) -> Any:
            if "disabled_tools" in data:
                data["disabled_tools"] = sorted({t.strip() for t in data["disabled_tools"] if t})
            if "instructions" in data:
                data["instructions"] = data["instructions"].strip()
            if not data:
                raise InvalidRequest("Send at least one setting to change.")
            tools = await tool_names() if tool_names else []
            return {**(await r.store.update_settings(data, s.login)).public(), "tools": tools}

        # Instructions can be long: the audit keeps whether they changed, not the text.
        audited = {k: ("(changed)" if k == "instructions" else v) for k, v in data.items()}
        return await respond(request, "admin.update_settings", audited, action)

    @router.get("/usage")
    async def usage(request: Request, days: int = 7) -> Any:
        """Calls, errors by kind, tokens and latency per provider and model."""
        days = max(1, min(days, 90))

        async def action(r: ProviderRegistry, s: OdooSession) -> Any:
            since = datetime.now(UTC) - timedelta(days=days)
            return {"days": days, "usage": await r.store.usage_summary(since)}

        return await respond(request, "admin.usage", {"days": days}, action)

    return router
