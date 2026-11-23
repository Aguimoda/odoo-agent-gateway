"""The web app (ADR 0019) and its sign-in (ADR 0018).

`/session` signs a person in with their Odoo login and API key, which stay on the server.
`/app` serves the built React app from the same origin, with a strict Content Security
Policy. Without a build, `/app` says how to make one and the API keeps working.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from odoo_agent_gateway.gateway import LOGIN_HEADER, Gateway
from odoo_agent_gateway.http_api import call_through_gateway, error_response, host_allowed
from odoo_agent_gateway.odoo import OdooError, OdooSession
from odoo_agent_gateway.web_sessions import (
    COOKIE_NAME,
    TICKET_LIFETIME,
    SessionsUnavailable,
    WebSessions,
    origin_allowed,
)

DEFAULT_WEB_DIR = Path(__file__).resolve().parent / "web_dist"


def content_security_policy(embed_origins: tuple[str, ...] = ()) -> str:
    """Only our own resources; framing only by the Odoo origins listed (ADR 0019, 0021)."""
    framing = "'self' " + " ".join(embed_origins) if embed_origins else "'none'"
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            f"frame-ancestors {framing}",
        ]
    )


CONTENT_SECURITY_POLICY = content_security_policy()
SECURITY_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
}
NOT_BUILT = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Odoo Agent Gateway</title>
<p>The web app is not built. From the repository root run:</p>
<pre>npm --prefix web ci
npm --prefix web run build</pre>
<p>The API works without it.</p></html>"""


class SignIn(BaseModel):
    login: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=1, max_length=500)


class Redeem(BaseModel):
    ticket: str = Field(min_length=1, max_length=200)


def _refused(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def build_session_router(
    gateway: Gateway,
    sessions: WebSessions | None,
    admin_group: str,
    allowed_hosts: tuple[str, ...],
    allowed_origins: tuple[str, ...],
    cookie_secure: bool | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/session", tags=["session"])

    async def whoami(session: OdooSession) -> dict[str, Any]:
        rows = await session.call("res.users", "read", [[session.uid], ["name"]])
        is_admin = await session.call("res.users", "has_group", [[session.uid], admin_group])
        return {
            "login": session.login,
            "uid": session.uid,
            "name": rows[0]["name"] if rows else session.login,
            "is_admin": bool(is_admin),
        }

    def precheck(request: Request) -> JSONResponse | None:
        if not host_allowed(request.headers.get("host", ""), allowed_hosts):
            return _refused(421, "misdirected", "Host not allowed.")
        origin = request.headers.get("origin")
        own = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin is not None and not origin_allowed(origin, allowed_origins, own):
            return _refused(403, "forbidden", "Request from another site refused.")
        if sessions is None:
            return _refused(
                503,
                SessionsUnavailable.code,
                "Web sign-in is not configured on this gateway: set GATEWAY_SECRET_KEYS.",
            )
        return None

    def with_cookie(request: Request, info: dict[str, Any], token: str) -> JSONResponse:
        response = JSONResponse(info)
        secure = cookie_secure if cookie_secure is not None else request.url.scheme == "https"
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=int(sessions.lifetime.total_seconds()),
            path="/",
            secure=secure,
            httponly=True,
            samesite="strict",
        )
        return response

    @router.post("")
    async def sign_in(request: Request, body: SignIn) -> Any:
        """Check the login and key with Odoo, then keep the key on the server."""
        if refused := precheck(request):
            return refused
        headers = {LOGIN_HEADER: body.login.strip(), "authorization": f"Bearer {body.api_key}"}
        created: dict[str, str] = {}

        async def action(session: OdooSession) -> dict[str, Any]:
            info = await whoami(session)
            created["token"] = await sessions.create(session.uid, session.login, session.api_key)
            return info

        try:  # audited as session.create; the key is never in the arguments
            info = await gateway.execute(headers, str(uuid.uuid4()), "session.create", {}, action)
        except OdooError as error:
            return error_response(error)
        return with_cookie(request, info, created["token"])

    @router.post("/ticket")
    async def ticket(request: Request, body: SignIn) -> Any:
        """Odoo's server hands over the person's assistant key; the browser gets a ticket.

        The key is checked with Odoo and kept encrypted, as for a sign-in. No cookie is set:
        the caller is Odoo's server, and the ticket works once, within 60 seconds (ADR 0021).
        """
        if refused := precheck(request):
            return refused
        headers = {LOGIN_HEADER: body.login.strip(), "authorization": f"Bearer {body.api_key}"}

        async def action(session: OdooSession) -> dict[str, Any]:
            value = await sessions.create_ticket(session.uid, session.login, session.api_key)
            return {"ticket": value, "expires_in": int(TICKET_LIFETIME.total_seconds())}

        try:  # audited as session.ticket; neither the key nor the ticket is in the arguments
            return await gateway.execute(headers, str(uuid.uuid4()), "session.ticket", {}, action)
        except OdooError as error:
            return error_response(error)

    @router.post("/redeem")
    async def redeem(request: Request, body: Redeem) -> Any:
        """The browser exchanges a ticket for the session cookie, once."""
        if refused := precheck(request):
            return refused
        token = await sessions.redeem(body.ticket)
        credentials = await sessions.resolve(token) if token else None
        if credentials is None:
            return _refused(401, "unauthenticated", "This link has expired: open the panel again.")
        headers = {
            LOGIN_HEADER: credentials.login,
            "authorization": f"Bearer {credentials.api_key}",
        }
        try:
            info = await gateway.execute(headers, str(uuid.uuid4()), "session.redeem", {}, whoami)
        except OdooError as error:
            await sessions.delete(token)
            return error_response(error)
        return with_cookie(request, info, token)

    @router.get("")
    async def current(request: Request) -> Any:
        """Who is signed in, and whether Odoo puts them in the admin group."""
        return await call_through_gateway(
            gateway, request, allowed_hosts, "session.read", {}, whoami
        )

    @router.delete("")
    async def sign_out(request: Request) -> Any:
        """Delete the session on the server and the cookie in the browser."""
        token = request.cookies.get(COOKIE_NAME)
        if sessions is not None and token:
            try:
                await sessions.delete(token)
            except SessionsUnavailable as error:
                return _refused(503, error.code, str(error))
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
        return response

    return router


def build_web_router(dist: Path, embed_origins: tuple[str, ...] = ()) -> APIRouter:
    """Serve the built app at /app, falling back to index.html for client-side routes."""
    router = APIRouter(include_in_schema=False)
    root = dist.resolve()
    security = dict(SECURITY_HEADERS)
    if embed_origins:  # Odoo may show the app in its panel; X-Frame-Options has no allow-list
        security["content-security-policy"] = content_security_policy(embed_origins)
        security.pop("x-frame-options")

    def headers(cache: str) -> dict[str, str]:
        return {**security, "cache-control": cache}

    @router.get("/")
    async def home() -> RedirectResponse:
        return RedirectResponse("/app/")

    @router.get("/app")
    async def app_root() -> RedirectResponse:
        return RedirectResponse("/app/")

    @router.get("/app/{path:path}")
    async def app_file(path: str) -> Any:
        index = root / "index.html"
        if not index.is_file():
            return HTMLResponse(NOT_BUILT, status_code=503, headers=headers("no-store"))
        if path:
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file() and candidate != index:
                immutable = path.startswith("assets/")
                cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
                return FileResponse(candidate, headers=headers(cache))
            if path.startswith("assets/"):
                return HTMLResponse("Not found", status_code=404, headers=headers("no-store"))
        return FileResponse(index, media_type="text/html", headers=headers("no-store"))

    return router
