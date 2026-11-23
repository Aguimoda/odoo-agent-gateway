"""The Odoo module acts as the person (ADR 0021), checked on its source.

Its behaviour is tested inside Odoo (odoo_addon/agent_gateway_connector/tests, run with
--test-enable in CI); this only guards rules that are easy to break by accident.
"""

import ast
import re
from pathlib import Path

ADDON = Path(__file__).resolve().parents[2] / "odoo_addon" / "agent_gateway_connector"


def python_sources():
    return sorted(ADDON.rglob("*.py"))


def test_the_module_never_uses_sudo_to_act():
    allowed = {'self.env["ir.config_parameter"].sudo()'}  # reading its own settings only
    found = []
    for path in python_sources():
        if "tests" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in re.finditer(r"[\w\.\[\]\"]+\.sudo\(([^)]*)\)", line):
                if match.group(1).strip() == "False":
                    continue  # explicitly dropping privileges
                if match.group(0) not in allowed:
                    found.append(f"{path.name}:{number}: {line.strip()}")
    assert found == []


def test_the_module_never_switches_user():
    for path in python_sources():
        if "tests" in path.parts:
            continue
        assert "with_user(" not in path.read_text(encoding="utf-8"), path.name


def test_the_manifest_is_valid_and_versioned_for_odoo_18():
    manifest = ast.literal_eval((ADDON / "__manifest__.py").read_text(encoding="utf-8"))
    assert manifest["version"].startswith("18.0.")
    assert manifest["installable"] is True
    for data in manifest["data"]:
        assert (ADDON / data).is_file(), data
    for asset in manifest["assets"]["web.assets_backend"]:
        assert (ADDON.parent / asset).is_file(), asset


def test_the_browser_code_never_handles_a_key():
    script = (ADDON / "static" / "src" / "assistant.js").read_text(encoding="utf-8")
    assert "api_key" not in script and "apikey" not in script.lower()
