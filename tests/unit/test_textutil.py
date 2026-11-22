import pytest

from odoo_agent_gateway.textutil import odoo_text


@pytest.mark.parametrize("value", [False, None, "", 0])
def test_empty_odoo_values_become_empty_text(value):
    assert odoo_text(value) == ""


def test_html_becomes_plain_lines():
    value = "<p>Returns within <b>30&nbsp;days</b>.</p><ul><li>Unused</li><li>Boxed</li></ul>"

    assert odoo_text(value) == "Returns within 30\xa0days.\nUnused\nBoxed"


def test_plain_text_is_kept_and_spaces_are_tidied():
    assert odoo_text("  Shipping   takes\t5 days  ") == "Shipping takes 5 days"


def test_script_like_text_is_returned_as_text_not_markup():
    assert odoo_text("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>") == "<script>alert(1)</script>"
