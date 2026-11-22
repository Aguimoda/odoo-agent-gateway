"""Run the gateway: `python -m odoo_agent_gateway`.

Reads ODOO_URL and ODOO_DB (required) plus optional GATEWAY_* settings from the
environment. Listens on 127.0.0.1:8000 unless GATEWAY_HOST / GATEWAY_PORT say otherwise.
"""

import os

import uvicorn

from odoo_agent_gateway.app import create_app


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("GATEWAY_HOST", "127.0.0.1"),
        port=int(os.environ.get("GATEWAY_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
