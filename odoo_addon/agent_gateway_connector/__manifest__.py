{
    "name": "AI assistant (Odoo Agent Gateway)",
    "summary": "Chat with an AI assistant that works as you, with your Odoo rights",
    "description": """
The assistant runs outside Odoo, in Odoo Agent Gateway. This module adds its button,
side panel, approvals inbox and settings to Odoo. After the person allows it, the module
creates a short-lived API key for them (as them, never as an administrator) and hands it
to the gateway server to server; the browser only gets a one-time ticket (ADR 0021).
""",
    "version": "18.0.0.8.0",
    "category": "Productivity",
    "author": "Daniel Moreno",
    "website": "https://github.com/Aguimoda/odoo-agent-gateway",
    "license": "Other OSI approved licence",
    "depends": ["base_setup", "web"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "views/res_config_settings_views.xml",
        "views/res_users_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "agent_gateway_connector/static/src/assistant.js",
            "agent_gateway_connector/static/src/assistant.xml",
            "agent_gateway_connector/static/src/assistant.scss",
        ],
    },
    "installable": True,
    "application": True,
}
