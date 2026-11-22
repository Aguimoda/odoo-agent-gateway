"""FastAPI application: `/health` plus the MCP endpoint at `/mcp`."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings

from odoo_agent_gateway import __version__
from odoo_agent_gateway.audit import AuditSink, PostgresAuditSink
from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.embeddings import FastEmbedEmbedder
from odoo_agent_gateway.knowledge import KnowledgeSearch
from odoo_agent_gateway.knowledge_store import PostgresKnowledgeStore
from odoo_agent_gateway.server import HttpClientFactory, OdooProvider, build_mcp_server
from odoo_agent_gateway.tools import Limits


def create_app(
    settings: Settings | None = None,
    http_client_factory: HttpClientFactory | None = None,
    audit_sink: AuditSink | None = None,
    knowledge: Any = None,
) -> FastAPI:
    """Build the application. A factory keeps tests isolated and configuration explicit."""
    settings = settings or Settings.from_env(os.environ)
    if audit_sink is None:
        if not settings.database_url:
            raise ValueError(
                "GATEWAY_DATABASE_URL is required: the gateway does not run without its "
                "audit log (ADR 0008)."
            )
        audit_sink = PostgresAuditSink(settings.database_url)
    factory = http_client_factory or (lambda: httpx2.AsyncClient(timeout=settings.odoo_timeout))
    provider = OdooProvider(settings, factory)
    knowledge_store: PostgresKnowledgeStore | None = None
    embedder: FastEmbedEmbedder | None = None
    if knowledge is None and settings.database_url:
        knowledge_store = PostgresKnowledgeStore(settings.database_url)
        embedder = FastEmbedEmbedder(cache_dir=settings.model_cache)
        limits = Limits(allowed_models=settings.allowed_models)
        knowledge = KnowledgeSearch(knowledge_store, embedder, limits)
    mcp_server = build_mcp_server(
        settings, factory, provider, audit=audit_sink, knowledge=knowledge
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
        if knowledge_store is not None:
            await knowledge_store.start()
        if embedder is not None:
            await embedder.embed(["warm up"])  # load the model now, not on the first question
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            await provider.aclose()
            await audit_sink.close()
            if knowledge_store is not None:
                await knowledge_store.close()

    app = FastAPI(title="Odoo Agent Gateway", version=__version__, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.mount("/", mcp_app)  # serves /mcp
    return app
