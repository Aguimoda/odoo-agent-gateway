"""The assistant's key, made as the person, after consent (ADR 0021).

Everything here runs as the signed-in person. The only sudo() reads this module's own
settings from ir.config_parameter, which ordinary users cannot read.
"""

import logging
import secrets
from datetime import timedelta

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

KEY_NAME = "Odoo Agent Gateway (assistant)"
MAX_KEYS = 5  # per person: one per device or browser, older ones are removed
PAGES = ("chat", "approvals", "admin")
PARAM = "agent_gateway_connector.%s"
TIMEOUT = 15
NOT_CONFIGURED = (
    "The assistant is not configured yet: ask an administrator (Settings → AI assistant)."
)


class ResUsers(models.Model):
    _inherit = "res.users"

    agent_gateway_consent = fields.Boolean(
        string="AI assistant allowed",
        help="The person allowed the AI assistant to act on their behalf, with their rights.",
        copy=False,
    )
    agent_gateway_consent_date = fields.Datetime(string="AI assistant allowed on", copy=False)

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            "agent_gateway_consent",
            "agent_gateway_consent_date",
        ]

    @property
    def SELF_WRITEABLE_FIELDS(self):
        # Each person decides about their own consent; nobody else's.
        return super().SELF_WRITEABLE_FIELDS + [
            "agent_gateway_consent",
            "agent_gateway_consent_date",
        ]

    # -- settings ----------------------------------------------------------------------------

    @api.model
    def _agent_gateway_settings(self):
        params = self.env["ir.config_parameter"].sudo()  # reading our own settings only
        hours = int(params.get_param(PARAM % "key_hours", 8) or 8)
        return {
            "public_url": (params.get_param(PARAM % "public_url") or "").rstrip("/"),
            "server_url": (params.get_param(PARAM % "server_url") or "").rstrip("/"),
            "hours": min(max(hours, 1), 24),
        }

    # -- called from the browser, as the person ------------------------------------------------

    @api.model
    def agent_gateway_status(self):
        settings = self._agent_gateway_settings()
        return {
            "configured": bool(settings["public_url"] and settings["server_url"]),
            "consent": self.env.user.sudo(False).agent_gateway_consent,
            "public_url": settings["public_url"],
        }

    @api.model
    def agent_gateway_accept(self):
        """The person allows the assistant to act on their behalf."""
        self.env.user.sudo(False).write(
            {"agent_gateway_consent": True, "agent_gateway_consent_date": fields.Datetime.now()}
        )
        return True

    @api.model
    def agent_gateway_ticket(self, page="chat"):
        """A one-time link for the panel: a new key, handed to the gateway server to server."""
        user = self.env.user.sudo(False)
        if page not in PAGES:
            raise UserError(_("Unknown assistant page."))
        if not user.agent_gateway_consent:
            raise UserError(_("Allow the assistant first."))
        settings = self._agent_gateway_settings()
        if not (settings["public_url"] and settings["server_url"]):
            raise UserError(_(NOT_CONFIGURED))

        key = self._agent_gateway_new_key(settings["hours"])
        try:
            response = requests.post(
                settings["server_url"] + "/session/ticket",
                json={"login": user.login, "api_key": key},
                timeout=TIMEOUT,
            )
            ticket = response.json().get("ticket") if response.status_code == 200 else None
        except (requests.RequestException, ValueError):
            response, ticket = None, None
        if not ticket:
            self._agent_gateway_drop_newest_key()
            _logger.warning(
                "Agent gateway refused or unreachable for %s: %s",
                user.login,
                getattr(response, "status_code", "no answer"),
            )
            raise UserError(_("The assistant could not be reached. Try again in a moment."))
        nonce = secrets.token_hex(4)  # a new address, so the panel reloads with the ticket
        return {"url": f"{settings['public_url']}/app/embed/{page}?open={nonce}#ticket={ticket}"}

    def agent_gateway_revoke(self):
        """Delete the person's assistant keys and their consent. Only ever for oneself."""
        user = self.env.user.sudo(False)  # env.user is privileged in Odoo: act as the person
        self.env["res.users.apikeys"].search(
            [("user_id", "=", user.id), ("name", "=", KEY_NAME)]
        )._remove()
        user.write({"agent_gateway_consent": False, "agent_gateway_consent_date": False})
        return True

    # -- the key ------------------------------------------------------------------------------

    def _agent_gateway_new_key(self, hours):
        """Create the key in its own transaction, committed at once so the gateway can use it."""
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, self.env.context)
            keys = env["res.users.apikeys"]
            own = keys.search([("user_id", "=", env.uid), ("name", "=", KEY_NAME)], order="id desc")
            own[MAX_KEYS - 1 :]._remove()
            expiration = fields.Datetime.now() + timedelta(hours=hours)
            try:
                return keys._generate("rpc", KEY_NAME, expiration)
            except ValidationError:  # longer than Odoo allows this person: use what it allows
                return keys._generate("rpc", KEY_NAME, fields.Datetime.now() + timedelta(hours=23))

    def _agent_gateway_drop_newest_key(self):
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, self.env.context)
            env["res.users.apikeys"].search(
                [("user_id", "=", env.uid), ("name", "=", KEY_NAME)], order="id desc", limit=1
            )._remove()
