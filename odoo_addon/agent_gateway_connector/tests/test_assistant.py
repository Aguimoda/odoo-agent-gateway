"""The connector, inside Odoo, as the person (ADR 0021). Run with Odoo's --test-enable."""

from datetime import timedelta
from unittest.mock import patch

import requests
from odoo import fields
from odoo.addons.agent_gateway_connector.models.res_users import KEY_NAME, MAX_KEYS
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

POST = "odoo.addons.agent_gateway_connector.models.res_users.requests.post"


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {"ticket": "t" * 43, "expires_in": 60}

    def json(self):
        return self._body


@tagged("post_install", "-at_install", "agent_gateway")
class TestAssistant(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("agent_gateway_connector.public_url", "http://127.0.0.1:8000")
        params.set_param("agent_gateway_connector.server_url", "http://gateway.test:8000")
        cls.ana = new_test_user(cls.env, login="aga_ana", groups="base.group_user")
        cls.luis = new_test_user(cls.env, login="aga_luis", groups="base.group_user")

    def setUp(self):
        super().setUp()
        # Keys are created in their own cursor (so the gateway can see them at once);
        # in tests that cursor must share the test transaction.
        self.registry.enter_test_mode(self.cr)
        self.addCleanup(self.registry.leave_test_mode)

    def as_ana(self):
        return self.env["res.users"].with_user(self.ana)

    def keys(self, user):
        return (
            self.env["res.users.apikeys"]
            .sudo()
            .search([("user_id", "=", user.id), ("name", "=", KEY_NAME)])
        )

    def test_status_says_whether_configured_and_consented(self):
        status = self.as_ana().agent_gateway_status()
        self.assertEqual(status["public_url"], "http://127.0.0.1:8000")
        self.assertTrue(status["configured"])
        self.assertFalse(status["consent"])
        self.assertEqual(status["login"], "aga_ana")
        self.assertNotIn("server_url", status)  # the browser only needs its own address

    def test_no_key_without_consent(self):
        """Scenario: sin consentimiento no hay clave."""
        with patch(POST) as post, self.assertRaises(UserError):
            self.as_ana().agent_gateway_ticket("chat")
        post.assert_not_called()
        self.assertFalse(self.keys(self.ana))

    def test_a_ticket_comes_from_a_short_lived_rpc_key_made_as_the_person(self):
        """Scenario: chat dentro de Odoo (clave de 8 horas, solo RPC)."""
        self.as_ana().agent_gateway_accept()
        with patch(POST, return_value=FakeResponse()) as post:
            result = self.as_ana().agent_gateway_ticket("chat")

        (key,) = self.keys(self.ana)
        self.assertEqual(key.scope, "rpc")
        self.assertLessEqual(
            key.expiration_date, fields.Datetime.now() + timedelta(hours=8, minutes=1)
        )
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, "http://gateway.test:8000/session/ticket")
        self.assertEqual(kwargs["json"]["login"], "aga_ana")
        self.assertEqual(len(kwargs["json"]["api_key"]), 40)  # a real key went to the gateway only
        self.assertTrue(result["url"].startswith("http://127.0.0.1:8000/app/embed/chat?"))
        self.assertTrue(result["url"].endswith("#ticket=" + "t" * 43))
        self.assertIn("as=aga_ana", result["url"])  # the panel knows whom it is for
        self.assertNotIn(kwargs["json"]["api_key"], str(result))  # never to the browser

    def test_only_known_pages_can_be_opened(self):
        self.as_ana().agent_gateway_accept()
        with patch(POST, return_value=FakeResponse()), self.assertRaises(UserError):
            self.as_ana().agent_gateway_ticket("../../evil")

    def test_an_unreachable_gateway_is_explained_and_leaves_no_key(self):
        self.as_ana().agent_gateway_accept()
        with (
            patch(POST, side_effect=requests.ConnectionError("down")),
            self.assertRaises(UserError),
        ):
            self.as_ana().agent_gateway_ticket("chat")
        self.assertFalse(self.keys(self.ana))

    def test_a_refused_key_is_explained_and_leaves_no_key(self):
        self.as_ana().agent_gateway_accept()
        refused = FakeResponse(401, {"error": "unauthenticated"})
        with patch(POST, return_value=refused), self.assertRaises(UserError):
            self.as_ana().agent_gateway_ticket("chat")
        self.assertFalse(self.keys(self.ana))

    def test_old_keys_are_pruned_and_others_are_left_alone(self):
        self.as_ana().agent_gateway_accept()
        self.env["res.users"].with_user(self.luis).agent_gateway_accept()
        with patch(POST, return_value=FakeResponse()):
            self.env["res.users"].with_user(self.luis).agent_gateway_ticket("chat")
            for _ in range(MAX_KEYS + 2):
                self.as_ana().agent_gateway_ticket("chat")
        self.assertEqual(len(self.keys(self.ana)), MAX_KEYS)
        self.assertEqual(len(self.keys(self.luis)), 1)

    def test_revoking_deletes_the_keys_and_the_consent(self):
        """Scenario: retirar el acceso."""
        self.as_ana().agent_gateway_accept()
        with patch(POST, return_value=FakeResponse()):
            self.as_ana().agent_gateway_ticket("chat")
        other = (
            self.env["res.users.apikeys"]
            .with_user(self.ana)
            ._generate("rpc", "Ana's own script", fields.Datetime.now() + timedelta(hours=1))
        )
        self.assertTrue(other)

        self.ana.with_user(self.ana).agent_gateway_revoke()
        self.assertFalse(self.keys(self.ana))
        self.assertFalse(self.ana.agent_gateway_consent)
        remaining = self.env["res.users.apikeys"].sudo().search([("user_id", "=", self.ana.id)])
        self.assertEqual(remaining.mapped("name"), ["Ana's own script"])  # only the assistant's go

    def test_revoking_only_ever_acts_on_oneself(self):
        self.env["res.users"].with_user(self.luis).agent_gateway_accept()
        with patch(POST, return_value=FakeResponse()):
            self.env["res.users"].with_user(self.luis).agent_gateway_ticket("chat")
        self.luis.with_user(self.ana).agent_gateway_revoke()  # Ana presses it on Luis's record
        self.assertEqual(len(self.keys(self.luis)), 1)
        self.assertTrue(self.luis.agent_gateway_consent)

    def test_not_configured_is_explained(self):
        self.env["ir.config_parameter"].sudo().set_param("agent_gateway_connector.server_url", "")
        self.as_ana().agent_gateway_accept()
        self.assertFalse(self.as_ana().agent_gateway_status()["configured"])
        with self.assertRaises(UserError):
            self.as_ana().agent_gateway_ticket("chat")
