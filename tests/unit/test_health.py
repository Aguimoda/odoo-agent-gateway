from fastapi.testclient import TestClient

from odoo_agent_gateway import __version__
from odoo_agent_gateway.app import create_app
from odoo_agent_gateway.audit import MemoryAuditSink
from odoo_agent_gateway.config import Settings

SETTINGS = Settings(odoo_url="http://odoo.test", odoo_db="demo")


def test_health_reports_ok_and_version():
    client = TestClient(create_app(SETTINGS, audit_sink=MemoryAuditSink()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_unknown_route_returns_404():
    client = TestClient(create_app(SETTINGS, audit_sink=MemoryAuditSink()))

    assert client.get("/does-not-exist").status_code == 404
