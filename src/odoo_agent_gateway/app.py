"""FastAPI application: `/health`, `/approvals`, `/admin` and MCP at `/mcp`."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings

from odoo_agent_gateway import __version__, tracing
from odoo_agent_gateway.admin import build_admin_router
from odoo_agent_gateway.approvals import build_approval_router
from odoo_agent_gateway.audit import AuditSink, PostgresAuditSink
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.embeddings import FastEmbedEmbedder
from odoo_agent_gateway.gateway import Gateway, HttpClientFactory, OdooProvider
from odoo_agent_gateway.knowledge import KnowledgeSearch
from odoo_agent_gateway.knowledge_store import PostgresKnowledgeStore
from odoo_agent_gateway.llm import ChatClient
from odoo_agent_gateway.proposal_store import PostgresProposalStore
from odoo_agent_gateway.proposals import ProposalService
from odoo_agent_gateway.provider_store import PostgresProviderStore
from odoo_agent_gateway.providers import ProviderRegistry
from odoo_agent_gateway.ratelimit import RateLimiter
from odoo_agent_gateway.secretbox import SecretBox
from odoo_agent_gateway.server import build_mcp_server
from odoo_agent_gateway.tools import Limits


def create_app(
    settings: Settings | None = None,
    http_client_factory: HttpClientFactory | None = None,
    audit_sink: AuditSink | None = None,
    knowledge: Any = None,
    proposals: Any = None,
    llm_http: httpx2.AsyncClient | None = None,
) -> FastAPI:
    """Build the application. A factory keeps tests isolated and configuration explicit."""
    settings = settings or Settings.from_env(os.environ)
    tracing.configure(settings.traces)  # off unless GATEWAY_TRACES is console or otlp
    if audit_sink is None:
        if not settings.database_url:
            raise ValueError(
                "GATEWAY_DATABASE_URL is required: the gateway does not run without its "
                "audit log (ADR 0008)."
            )
        audit_sink = PostgresAuditSink(settings.database_url)
    factory = http_client_factory or (lambda: httpx2.AsyncClient(timeout=settings.odoo_timeout))
    provider = OdooProvider(settings, factory)
    limits = Limits(allowed_models=settings.allowed_models)

    knowledge_store: PostgresKnowledgeStore | None = None
    embedder: FastEmbedEmbedder | None = None
    if knowledge is None and settings.database_url:
        knowledge_store = PostgresKnowledgeStore(settings.database_url)
        embedder = FastEmbedEmbedder(cache_dir=settings.model_cache)
        knowledge = KnowledgeSearch(
            knowledge_store, embedder, limits, min_score=settings.knowledge_min_score
        )

    proposal_store: PostgresProposalStore | None = None
    if proposals is None and settings.database_url:
        proposal_store = PostgresProposalStore(settings.database_url)
        proposals = ProposalService(proposal_store, limits)

    # Providers and the agent need the database and the master keys (ADR 0015).
    provider_store: PostgresProviderStore | None = None
    registry: ProviderRegistry | None = None
    llm_client = llm_http
    if settings.database_url and settings.secret_keys:
        provider_store = PostgresProviderStore(settings.database_url)
        llm_client = llm_client or httpx2.AsyncClient(follow_redirects=False)
        registry = ProviderRegistry(
            provider_store,
            SecretBox.from_env(settings.secret_keys),
            ChatClient(llm_client),
            local_hosts=settings.local_provider_hosts,
        )

    # One gateway path, one rate limiter, for every channel.
    gateway = Gateway(provider, audit_sink, RateLimiter(settings.rate_limit_per_minute))
    mcp_server = build_mcp_server(
        settings,
        factory,
        audit=audit_sink,
        knowledge=knowledge,
        proposals=proposals,
        gateway=gateway,
    )
    mcp_app = mcp_server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=list(settings.allowed_origins),
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await audit_sink.start()  # applies the schema; fails start-up if the DB is down
        for store in (knowledge_store, proposal_store, provider_store):
            if store is not None:
                await store.start()
        if embedder is not None:
            await embedder.embed(["warm up"])  # load the model now, not on the first question
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            await provider.aclose()
            await audit_sink.close()
            if llm_client is not None:
                await llm_client.aclose()
            for store in (knowledge_store, proposal_store, provider_store):
                if store is not None:
                    await store.close()

    app = FastAPI(title="Odoo Agent Gateway", version=__version__, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(build_approval_router(gateway, proposals, settings.allowed_hosts))
    app.include_router(
        build_admin_router(gateway, registry, settings.admin_group, settings.allowed_hosts)
    )
    app.mount("/", mcp_app)  # serves /mcp; mounted last so it does not shadow other routes
    return app
