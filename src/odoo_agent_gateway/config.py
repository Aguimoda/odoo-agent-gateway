"""Gateway settings, read from environment variables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from odoo_agent_gateway.tools import DEFAULT_ALLOWED_MODELS

LOCAL_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
LOCAL_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")


@dataclass(frozen=True)
class Settings:
    odoo_url: str
    odoo_db: str
    allowed_models: frozenset[str] = DEFAULT_ALLOWED_MODELS
    allowed_hosts: tuple[str, ...] = LOCAL_HOSTS
    allowed_origins: tuple[str, ...] = LOCAL_ORIGINS
    odoo_timeout: float = 30.0
    database_url: str | None = None
    rate_limit_per_minute: int = 60
    model_cache: str = ".cache/models"
    knowledge_min_score: float = 0.42  # see knowledge.DEFAULT_MIN_SCORE
    traces: str = "none"  # none, console or otlp (ADR 0014)
    admin_group: str = "base.group_system"  # Odoo group that administers (ADR 0015)
    secret_keys: str | None = None  # master keys for provider keys (ADR 0015)
    local_provider_hosts: frozenset[str] = frozenset()  # http allowed (local models)
    agent_messages_per_minute: int = 10
    session_idle_minutes: int = 120  # web sessions (ADR 0018)
    session_hours: int = 12
    cookie_secure: bool | None = None  # None: Secure when the request came over https
    web_dir: str | None = None  # built web app (ADR 0019); default: the package's web_dist

    def __repr__(self) -> str:
        # The database URL contains a password and the secret keys are secret: never print.
        return f"Settings(odoo_url={self.odoo_url!r}, odoo_db={self.odoo_db!r})"

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Settings:
        missing = [name for name in ("ODOO_URL", "ODOO_DB") if not environ.get(name)]
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")
        values: dict = {"odoo_url": environ["ODOO_URL"], "odoo_db": environ["ODOO_DB"]}
        if models := _split(environ.get("GATEWAY_ALLOWED_MODELS")):
            values["allowed_models"] = frozenset(models)
        if hosts := _split(environ.get("GATEWAY_ALLOWED_HOSTS")):
            values["allowed_hosts"] = tuple(hosts)
        if origins := _split(environ.get("GATEWAY_ALLOWED_ORIGINS")):
            values["allowed_origins"] = tuple(origins)
        if timeout := environ.get("GATEWAY_ODOO_TIMEOUT"):
            values["odoo_timeout"] = float(timeout)
        if database_url := environ.get("GATEWAY_DATABASE_URL"):
            values["database_url"] = database_url
        if rate_limit := environ.get("GATEWAY_RATE_LIMIT_PER_MINUTE"):
            values["rate_limit_per_minute"] = int(rate_limit)
        if model_cache := environ.get("GATEWAY_MODEL_CACHE"):
            values["model_cache"] = model_cache
        if min_score := environ.get("GATEWAY_KNOWLEDGE_MIN_SCORE"):
            values["knowledge_min_score"] = float(min_score)
        if traces := environ.get("GATEWAY_TRACES"):
            values["traces"] = traces
        if admin_group := environ.get("GATEWAY_ADMIN_GROUP"):
            values["admin_group"] = admin_group.strip()
        if secret_keys := environ.get("GATEWAY_SECRET_KEYS"):
            values["secret_keys"] = secret_keys
        if local_hosts := _split(environ.get("GATEWAY_LOCAL_PROVIDER_HOSTS")):
            values["local_provider_hosts"] = frozenset(h.lower() for h in local_hosts)
        if per_minute := environ.get("GATEWAY_AGENT_MESSAGES_PER_MINUTE"):
            values["agent_messages_per_minute"] = int(per_minute)
        if idle := environ.get("GATEWAY_SESSION_IDLE_MINUTES"):
            values["session_idle_minutes"] = int(idle)
        if hours := environ.get("GATEWAY_SESSION_HOURS"):
            values["session_hours"] = int(hours)
        if secure := environ.get("GATEWAY_COOKIE_SECURE"):
            values["cookie_secure"] = _flag(secure, "GATEWAY_COOKIE_SECURE")
        if web_dir := environ.get("GATEWAY_WEB_DIR"):
            values["web_dir"] = web_dir
        return cls(**values)


def _flag(value: str, name: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]
