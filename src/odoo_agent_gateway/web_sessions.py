"""Web sessions (ADR 0018): the Odoo key stays on the server, the browser gets a cookie.

The browser holds a random 256-bit session id in an HttpOnly, SameSite=Strict cookie. The
server keeps only the SHA-256 of that id, the Odoo uid and login, and the person's key
encrypted with the master keys (ADR 0015), bound to the id hash as associated data. A
middleware turns a valid session into the same headers an agent sends, so every request
still runs through Odoo with the person's own key.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

import asyncpg

from odoo_agent_gateway.gateway import LOGIN_HEADER
from odoo_agent_gateway.migrations import apply_migrations
from odoo_agent_gateway.odoo import OdooError
from odoo_agent_gateway.secretbox import SecretBox, SecretError

COOKIE_NAME = "oag_session"
SESSION_PATHS = ("/agent", "/approvals", "/admin", "/session")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class SessionsUnavailable(OdooError):
    code = "sessions_unavailable"


@dataclass(frozen=True)
class SessionRow:
    id_hash: bytes
    odoo_uid: int
    login: str
    key_encrypted: bytes
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class Credentials:
    login: str
    uid: int
    api_key: str

    def __repr__(self) -> str:
        return f"Credentials(login={self.login!r}, uid={self.uid})"  # never the key


class SessionStorage(Protocol):
    async def insert(self, row: SessionRow) -> None: ...
    async def get(self, id_hash: bytes) -> SessionRow | None: ...
    async def touch(self, id_hash: bytes, at: datetime) -> None: ...
    async def delete(self, id_hash: bytes) -> None: ...
    async def purge(self, now: datetime, idle_before: datetime) -> int: ...


def hash_id(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii", "replace")).digest()


def _context(id_hash: bytes) -> str:
    return "web-session:" + id_hash.hex()


class WebSessions:
    """Creates and resolves sessions. Storage is a small protocol so the rules are testable."""

    def __init__(
        self,
        storage: SessionStorage,
        box: SecretBox,
        idle: timedelta = timedelta(hours=2),
        lifetime: timedelta = timedelta(hours=12),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.storage = storage
        self._box = box
        self.idle = idle
        self.lifetime = lifetime
        self._clock = clock

    def __repr__(self) -> str:
        return "WebSessions()"

    async def create(self, uid: int, login: str, api_key: str) -> str:
        """Store a new session and return the token for the cookie."""
        now = self._clock()
        await self.storage.purge(now, now - self.idle)
        token = secrets.token_urlsafe(32)
        id_hash = hash_id(token)
        await self.storage.insert(
            SessionRow(
                id_hash=id_hash,
                odoo_uid=uid,
                login=login,
                key_encrypted=self._box.encrypt(api_key, _context(id_hash)),
                created_at=now,
                last_seen_at=now,
                expires_at=now + self.lifetime,
            )
        )
        return token

    async def resolve(self, token: str) -> Credentials | None:
        """The credentials behind a cookie, or None when it is unknown or expired."""
        if not token or len(token) > 200:
            return None
        id_hash = hash_id(token)
        row = await self.storage.get(id_hash)
        if row is None:
            return None
        now = self._clock()
        if now >= row.expires_at or now - row.last_seen_at >= self.idle:
            await self.storage.delete(id_hash)
            return None
        try:
            api_key = self._box.decrypt(row.key_encrypted, _context(id_hash))
        except SecretError:
            return None  # a master key was removed: sign in again
        if now - row.last_seen_at >= timedelta(minutes=1):  # one write a minute at most
            await self.storage.touch(id_hash, now)
        return Credentials(login=row.login, uid=row.odoo_uid, api_key=api_key)

    async def delete(self, token: str) -> None:
        if token and len(token) <= 200:
            await self.storage.delete(hash_id(token))


class PostgresSessionStorage:
    def __init__(self, dsn: str, timeout: float = 10.0) -> None:
        self._dsn = dsn
        self._timeout = timeout
        self._pool: asyncpg.Pool | None = None

    def __repr__(self) -> str:
        return "PostgresSessionStorage()"  # the DSN contains a password

    async def start(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=5, timeout=self._timeout
            )
            async with self._pool.acquire() as connection:
                await apply_migrations(connection)
        except (OSError, asyncpg.PostgresError, TimeoutError) as error:
            raise SessionsUnavailable("The sessions database could not be reached.") from error

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _ready(self) -> asyncpg.Pool:
        if self._pool is None:
            raise SessionsUnavailable("The sessions store is not started.")
        return self._pool

    async def _run(self, method: str, query: str, *args: Any) -> Any:
        try:
            return await getattr(self._ready(), method)(query, *args)
        except (OSError, asyncpg.PostgresError, TimeoutError) as error:
            raise SessionsUnavailable("The sessions database could not be reached.") from error

    async def insert(self, row: SessionRow) -> None:
        await self._run(
            "execute",
            "insert into web_sessions (id_hash, odoo_uid, login, key_encrypted, created_at, "
            "last_seen_at, expires_at) values ($1, $2, $3, $4, $5, $6, $7)",
            row.id_hash,
            row.odoo_uid,
            row.login,
            row.key_encrypted,
            row.created_at,
            row.last_seen_at,
            row.expires_at,
        )

    async def get(self, id_hash: bytes) -> SessionRow | None:
        row = await self._run(
            "fetchrow",
            "select id_hash, odoo_uid, login, key_encrypted, created_at, last_seen_at, "
            "expires_at from web_sessions where id_hash = $1",
            id_hash,
        )
        return SessionRow(**dict(row)) if row else None

    async def touch(self, id_hash: bytes, at: datetime) -> None:
        await self._run(
            "execute", "update web_sessions set last_seen_at = $2 where id_hash = $1", id_hash, at
        )

    async def delete(self, id_hash: bytes) -> None:
        await self._run("execute", "delete from web_sessions where id_hash = $1", id_hash)

    async def purge(self, now: datetime, idle_before: datetime) -> int:
        result = await self._run(
            "execute",
            "delete from web_sessions where expires_at <= $1 or last_seen_at <= $2",
            now,
            idle_before,
        )
        return int(result.split()[-1])


# -- cookie and origin helpers -----------------------------------------------------------------


def cookie_value(headers: Iterable[tuple[bytes, bytes]], name: str = COOKIE_NAME) -> str | None:
    for key, value in headers:
        if key.lower() != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            cookie_name, _, cookie = part.strip().partition("=")
            if cookie_name == name and cookie:
                return cookie
    return None


def origin_allowed(origin: str, patterns: Iterable[str], own_origin: str | None = None) -> bool:
    """Same 'name:*' pattern rules as hosts. The request's own origin always passes."""
    origin = (origin or "").strip().lower().rstrip("/")
    if not origin or origin == "null":
        return False
    if own_origin and origin == own_origin.lower():
        return True
    for pattern in patterns:
        pattern = pattern.lower().rstrip("/")
        if pattern.endswith(":*"):
            base = pattern[:-2]
            if origin == base or origin.startswith(base + ":"):
                return True
        elif origin == pattern:
            return True
    return False


def own_origin(scope: dict[str, Any]) -> str | None:
    host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
    if not host or urlsplit(f"//{host}").hostname is None:
        return None
    return f"{scope.get('scheme', 'http')}://{host}"


async def _json(send: Callable[[dict], Awaitable[None]], status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class WebSessionMiddleware:
    """Turns the session cookie into the person's headers, only for the web APIs.

    `/mcp` and every other path are left untouched: agents keep sending their own headers.
    A request with its own Authorization header is left untouched too.
    """

    def __init__(
        self, app: Any, sessions: WebSessions | None, allowed_origins: Iterable[str]
    ) -> None:
        self.app = app
        self.sessions = sessions
        self.allowed_origins = tuple(allowed_origins)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or self.sessions is None
            or not any(
                scope["path"] == p or scope["path"].startswith(p + "/") for p in SESSION_PATHS
            )
        ):
            await self.app(scope, receive, send)
            return
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
        token = cookie_value(headers)
        if token is None or any(key.lower() == b"authorization" for key, _ in headers):
            await self.app(scope, receive, send)
            return

        if scope["method"] not in SAFE_METHODS:
            origin = dict(headers).get(b"origin", b"").decode("latin-1")
            if not origin_allowed(origin, self.allowed_origins, own_origin(scope)):
                await _json(
                    send,
                    403,
                    {"error": "forbidden", "message": "Request from another site refused."},
                )
                return

        try:
            credentials = await self.sessions.resolve(token)
        except SessionsUnavailable as error:
            await _json(send, 503, {"error": error.code, "message": str(error)})
            return
        if credentials is not None:
            headers = [(k, v) for k, v in headers if k.lower() != LOGIN_HEADER.encode()]
            headers.append((LOGIN_HEADER.encode(), credentials.login.encode()))
            headers.append((b"authorization", f"Bearer {credentials.api_key}".encode()))
            scope = {**scope, "headers": headers, "web_session": True}
        await self.app(scope, receive, send)
