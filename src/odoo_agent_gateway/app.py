"""FastAPI application factory for the gateway."""

from fastapi import FastAPI

from odoo_agent_gateway import __version__


def create_app() -> FastAPI:
    """Build the application. A factory keeps tests isolated and configuration explicit."""
    app = FastAPI(title="Odoo Agent Gateway", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
