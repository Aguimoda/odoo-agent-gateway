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
        }
    )

    assert settings.odoo_url == "http://127.0.0.1:8069"
    assert settings.odoo_db == "demo"
    assert settings.allowed_models == frozenset({"sale.order", "res.partner"})
    assert settings.allowed_hosts == ("gateway.example.com",)


def test_defaults_are_safe():
    settings = Settings.from_env({"ODOO_URL": "http://odoo", "ODOO_DB": "demo"})

    assert settings.allowed_models == DEFAULT_ALLOWED_MODELS
    assert settings.allowed_hosts == ("127.0.0.1:*", "localhost:*", "[::1]:*")


@pytest.mark.parametrize("missing", ["ODOO_URL", "ODOO_DB"])
def test_missing_required_settings_fail_clearly(missing):
    environ = {"ODOO_URL": "http://odoo", "ODOO_DB": "demo"}
    del environ[missing]

    with pytest.raises(ValueError, match=missing):
        Settings.from_env(environ)
