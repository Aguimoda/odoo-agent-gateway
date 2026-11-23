import pytest

from odoo_agent_gateway.config import Settings
from odoo_agent_gateway.tools import DEFAULT_ALLOWED_MODELS


def test_settings_read_the_environment():
    settings = Settings.from_env(
        {
            "ODOO_URL": "http://127.0.0.1:8069",
            "ODOO_DB": "demo",
            "GATEWAY_ALLOWED_MODELS": "sale.order, res.partner",
            "GATEWAY_ALLOWED_HOSTS": "gateway.example.com",
            "GATEWAY_DATABASE_URL": "postgresql://gateway@db/gateway",
            "GATEWAY_RATE_LIMIT_PER_MINUTE": "30",
        }
    )

    assert settings.database_url == "postgresql://gateway@db/gateway"
    assert settings.rate_limit_per_minute == 30

    assert settings.odoo_url == "http://127.0.0.1:8069"
    assert settings.odoo_db == "demo"
    assert settings.allowed_models == frozenset({"sale.order", "res.partner"})
    assert settings.allowed_hosts == ("gateway.example.com",)


def test_defaults_are_safe():
    settings = Settings.from_env({"ODOO_URL": "http://odoo", "ODOO_DB": "demo"})

    assert settings.allowed_models == DEFAULT_ALLOWED_MODELS
    assert settings.allowed_hosts == ("127.0.0.1:*", "localhost:*", "[::1]:*")
    assert settings.database_url is None
    assert settings.rate_limit_per_minute == 60


@pytest.mark.parametrize("missing", ["ODOO_URL", "ODOO_DB"])
def test_missing_required_settings_fail_clearly(missing):
    environ = {"ODOO_URL": "http://odoo", "ODOO_DB": "demo"}
    del environ[missing]

    with pytest.raises(ValueError, match=missing):
        Settings.from_env(environ)


def test_the_knowledge_threshold_defaults_to_the_calibrated_value_and_can_be_overridden():
    from odoo_agent_gateway.knowledge import DEFAULT_MIN_SCORE

    default = Settings.from_env({"ODOO_URL": "http://odoo", "ODOO_DB": "demo"})
    custom = Settings.from_env(
        {"ODOO_URL": "http://odoo", "ODOO_DB": "demo", "GATEWAY_KNOWLEDGE_MIN_SCORE": "0.3"}
    )

    assert default.knowledge_min_score == DEFAULT_MIN_SCORE == 0.42
    assert custom.knowledge_min_score == 0.3


def test_agent_settings_and_their_defaults():
    defaults = Settings.from_env({"ODOO_URL": "http://odoo", "ODOO_DB": "demo"})
    assert defaults.admin_group == "base.group_system"
    assert defaults.secret_keys is None
    assert defaults.local_provider_hosts == frozenset()
    assert defaults.agent_messages_per_minute == 10

    settings = Settings.from_env(
        {
            "ODOO_URL": "http://odoo",
            "ODOO_DB": "demo",
            "GATEWAY_ADMIN_GROUP": "base.group_erp_manager",
            "GATEWAY_SECRET_KEYS": "fake-master-key-for-tests",
            "GATEWAY_LOCAL_PROVIDER_HOSTS": "Ollama, llm-box",
            "GATEWAY_AGENT_MESSAGES_PER_MINUTE": "5",
        }
    )
    assert settings.admin_group == "base.group_erp_manager"
    assert settings.local_provider_hosts == frozenset({"ollama", "llm-box"})
    assert settings.agent_messages_per_minute == 5
    assert "fake-master-key-for-tests" not in repr(settings)


def test_web_session_settings():
    defaults = Settings.from_env({"ODOO_URL": "http://odoo:8069", "ODOO_DB": "demo"})
    assert (defaults.session_idle_minutes, defaults.session_hours) == (120, 12)
    assert defaults.cookie_secure is None and defaults.web_dir is None
    custom = Settings.from_env(
        {
            "ODOO_URL": "http://odoo:8069",
            "ODOO_DB": "demo",
            "GATEWAY_SESSION_IDLE_MINUTES": "30",
            "GATEWAY_SESSION_HOURS": "8",
            "GATEWAY_COOKIE_SECURE": "true",
            "GATEWAY_WEB_DIR": "/srv/web",
        }
    )
    assert (custom.session_idle_minutes, custom.session_hours) == (30, 8)
    assert custom.cookie_secure is True and custom.web_dir == "/srv/web"
    with pytest.raises(ValueError, match="GATEWAY_COOKIE_SECURE"):
        Settings.from_env({"ODOO_URL": "x", "ODOO_DB": "demo", "GATEWAY_COOKIE_SECURE": "maybe"})


def test_embed_origins_default_to_none_and_can_list_odoo():
    """ADR 0021: no one may frame the app unless Odoo is listed."""
    base = {"ODOO_URL": "http://odoo:8069", "ODOO_DB": "demo"}
    assert Settings.from_env(base).embed_origins == ()
    custom = Settings.from_env(
        {**base, "GATEWAY_EMBED_ORIGINS": "http://127.0.0.1:8069, https://odoo.example.com/"}
    )
    assert custom.embed_origins == ("http://127.0.0.1:8069", "https://odoo.example.com")
