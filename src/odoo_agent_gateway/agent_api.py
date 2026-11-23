"""The assistant API (ADR 0016): models, conversations and streamed answers.

Every request runs as the person on the shared Gateway path. For a message, that path does
the checks (credentials, limits, owner of the conversation) and writes the audit row before
the answer starts streaming; each tool call then gets its own audit row through MCP.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from odoo_agent_gateway.assistant import AgentService, Prepared
from odoo_agent_gateway.gateway import Gateway
from odoo_agent_gateway.http_api import call_through_gateway
from odoo_agent_gateway.odoo import OdooSession, RecordNotFound
from odoo_agent_gateway.provider_store import ProvidersUnavailable


class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class MessageIn(BaseModel):
    content: str = Field(max_length=8000)
    model_id: int | None = None


class RetryIn(BaseModel):
    model_id: int | None = None


STREAM_HEADERS = {"cache-control": "no-cache", "x-accel-buffering": "no"}


def build_agent_router(
    gateway: Gateway, service: AgentService | None, allowed_hosts: tuple[str, ...]
) -> APIRouter:
    router = APIRouter(prefix="/agent", tags=["agent"])

    async def respond(
        request: Request,
        tool: str,
        arguments: dict[str, Any],
        action: Callable[[AgentService, OdooSession], Awaitable[Any]],
    ) -> Any:
        async def run(session: OdooSession) -> Any:
            if service is None:
                raise ProvidersUnavailable(
                    "The assistant is not configured on this gateway: set GATEWAY_SECRET_KEYS."
                )
            return await action(service, session)

        return await call_through_gateway(gateway, request, allowed_hosts, tool, arguments, run)

    async def answer(request: Request, tool: str, arguments: dict[str, Any], prepare) -> Any:
        prepared = await respond(request, tool, arguments, prepare)
        if not isinstance(prepared, Prepared):
            return prepared  # an error response
        return StreamingResponse(
            service.stream(prepared, request.headers),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
        )

    @router.get("/models")
    async def models(request: Request) -> Any:
        """Models available now, and the default one."""
        return await respond(request, "agent.models", {}, lambda s, _: s.models())

    @router.get("/conversations")
    async def conversations(request: Request) -> Any:
        async def action(s: AgentService, session: OdooSession) -> Any:
            found = await s.conversations.list_for(session.uid)
            return {"conversations": [c.public() for c in found]}

        return await respond(request, "agent.conversations", {}, action)

    @router.post("/conversations")
    async def create(request: Request, body: ConversationIn | None = None) -> Any:
        title = body.title if body else None
        return await respond(
            request,
            "agent.create_conversation",
            {},
            lambda s, session: s.create_conversation(session, title),
        )

    @router.get("/conversations/{conversation_id}")
    async def read(conversation_id: str, request: Request) -> Any:
        async def action(s: AgentService, session: OdooSession) -> Any:
            conversation = await s.conversations.get(conversation_id, session.uid)
            messages = await s.conversations.messages(conversation_id, session.uid)
            return {**conversation.public(), "messages": [m.public() for m in messages]}

        return await respond(
            request, "agent.conversation", {"conversation_id": conversation_id}, action
        )

    @router.delete("/conversations/{conversation_id}")
    async def delete(conversation_id: str, request: Request) -> Any:
        async def action(s: AgentService, session: OdooSession) -> Any:
            if not await s.conversations.delete(conversation_id, session.uid):
                raise RecordNotFound("There is no conversation with that id.")
            return {"deleted": True, "conversation_id": conversation_id}

        return await respond(
            request, "agent.delete_conversation", {"conversation_id": conversation_id}, action
        )

    @router.post("/conversations/{conversation_id}/messages")
    async def message(conversation_id: str, request: Request, body: MessageIn) -> Any:
        """Send a message; the answer streams back as Server-Sent Events."""
        # The audit keeps the size of the message, not its text.
        arguments = {
            "conversation_id": conversation_id,
            "model_id": body.model_id,
            "characters": len(body.content),
        }
        return await answer(
            request,
            "agent.message",
            arguments,
            lambda s, session: s.prepare(session, conversation_id, body.content, body.model_id),
        )

    @router.post("/conversations/{conversation_id}/retry")
    async def retry(conversation_id: str, request: Request, body: RetryIn | None = None) -> Any:
        """Answer the last message again, for example with another model after a failure."""
        model_id = body.model_id if body else None
        return await answer(
            request,
            "agent.retry",
            {"conversation_id": conversation_id, "model_id": model_id},
            lambda s, session: s.prepare(session, conversation_id, None, model_id, retry=True),
        )

    return router
