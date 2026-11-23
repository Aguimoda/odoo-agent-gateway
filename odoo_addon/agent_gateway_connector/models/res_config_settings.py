from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    agent_gateway_public_url = fields.Char(
        string="Gateway address for browsers",
        config_parameter="agent_gateway_connector.public_url",
        help="Where people's browsers open the assistant, for example https://assistant.example.com.",
    )
    agent_gateway_server_url = fields.Char(
        string="Gateway address for the Odoo server",
        config_parameter="agent_gateway_connector.server_url",
        help="Where this Odoo server reaches the gateway; it can differ from the browsers' "
        "address, for example inside Docker.",
    )
    agent_gateway_key_hours = fields.Integer(
        string="Assistant key duration (hours)",
        config_parameter="agent_gateway_connector.key_hours",
        default=8,
        help="How long each assistant key lives. Odoo limits it to one day for ordinary users "
        "unless an administrator allows longer.",
    )
