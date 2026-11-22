from typing import Any

import pytest

from odoo_agent_gateway.odoo import AccessDenied, InvalidRequest, RecordNotFound
from odoo_agent_gateway.tools import Limits, ReadTools

pytestmark = pytest.mark.anyio

ALLOWED = ("res.partner", "sale.order")


class FakeSession:
    """Stands in for OdooSession. `answers` maps (model, method) to a value or a callable."""

    def __init__(self, answers: dict[tuple[str, str], Any] | None = None, uid: int = 8):
        self.uid = uid
        self.login = "ana"
        self.answers = answers or {}
        self.calls: list[tuple[str, str, list, dict]] = []

    async def call(self, model, method, args=None, kwargs=None):
        args, kwargs = args or [], kwargs or {}
        self.calls.append((model, method, args, kwargs))
        answer = self.answers.get((model, method))
        if isinstance(answer, Exception):
            raise answer
        return answer(args, kwargs) if callable(answer) else answer


def tools(session: FakeSession, **limits) -> ReadTools:
    limits.setdefault("allowed_models", frozenset(ALLOWED))
    return ReadTools(session, Limits(**limits))


# --- allowlist and input validation -------------------------------------------------------


@pytest.mark.parametrize("model", ["hr.employee", "res.users", "ir.config_parameter", ""])
async def test_models_outside_the_allowlist_are_rejected_without_calling_odoo(model):
    session = FakeSession()

    with pytest.raises(InvalidRequest):
        await tools(session).search_records(model)
    assert session.calls == []


@pytest.mark.parametrize(
    "domain",
    [
        [["partner_id.name", "=", "Acme"]],  # dotted path
        [["name", "=like", "%"], ["amount_total", "~", 3]],  # unknown operator
        [["name", "="]],  # malformed term
        ["or", ["name", "=", "x"]],  # unknown logical operator
        "[('name','=','x')]",  # string instead of a list
        [["name", "in", [["nested"]]]],  # nested lists as a value
    ],
)
async def test_unsafe_or_malformed_domains_are_rejected(domain):
    session = FakeSession()

    with pytest.raises(InvalidRequest):
        await tools(session).search_records("sale.order", domain=domain)
    assert session.calls == []


async def test_a_valid_domain_with_logical_operators_reaches_odoo_unchanged():
    domain = ["|", ["state", "=", "sale"], "!", ["amount_total", "<", 100]]
    session = FakeSession({("sale.order", "search_read"): []})

    await tools(session).search_records("sale.order", domain=domain)

    _, _, args, _ = session.calls[0]
    assert args == [domain]


@pytest.mark.parametrize(
    "fields", [["partner_id.name"], [f"f{i}" for i in range(21)], ["Bad Name"]]
)
async def test_invalid_field_lists_are_rejected(fields):
    session = FakeSession()

    with pytest.raises(InvalidRequest):
        await tools(session).search_records("sale.order", fields=fields)
    assert session.calls == []


async def test_order_must_be_plain_field_names_with_a_direction():
    session = FakeSession()

    with pytest.raises(InvalidRequest):
        await tools(session).search_records("sale.order", order="name; drop table")


# --- search_records ------------------------------------------------------------------------


async def test_search_returns_only_id_and_display_name_when_no_fields_are_named():
    session = FakeSession({("sale.order", "search_read"): [{"id": 21, "display_name": "S00021"}]})

    result = await tools(session).search_records("sale.order")

    _, _, _, kwargs = session.calls[0]
    assert kwargs["fields"] == ["display_name"]
    assert result["records"] == [{"id": 21, "display_name": "S00021"}]
    assert result["has_more"] is False


async def test_search_caps_at_fifty_records_and_reports_that_more_exist():
    rows = [{"id": i, "display_name": f"S{i}"} for i in range(1, 52)]
    session = FakeSession(
        {("sale.order", "search_read"): lambda args, kwargs: rows[: kwargs["limit"]]}
    )

    result = await tools(session).search_records("sale.order", limit=500)

    _, _, _, kwargs = session.calls[0]
    assert kwargs["limit"] == 51  # one extra row only to detect "has more"
    assert len(result["records"]) == 50
    assert result["has_more"] is True


async def test_long_text_values_are_cut_and_flagged():
    long_note = "x" * 5000
    session = FakeSession(
        {("res.partner", "search_read"): [{"id": 1, "display_name": "Acme", "comment": long_note}]}
    )

    result = await tools(session).search_records("res.partner", fields=["display_name", "comment"])

    assert len(result["records"][0]["comment"]) < 2100
    assert result["truncated"] is True


async def test_results_are_marked_as_data_not_instructions():
    session = FakeSession({("sale.order", "search_read"): []})

    result = await tools(session).search_records("sale.order")

    assert "not instructions" in result["notice"]


async def test_odoo_access_errors_reach_the_caller_unchanged():
    session = FakeSession({("sale.order", "search_read"): AccessDenied("denied")})

    with pytest.raises(AccessDenied):
        await tools(session).search_records("sale.order")


# --- read_record ---------------------------------------------------------------------------


async def test_read_record_returns_one_record():
    session = FakeSession({("sale.order", "read"): [{"id": 21, "display_name": "S00021"}]})

    result = await tools(session).read_record("sale.order", 21)

    assert result["record"] == {"id": 21, "display_name": "S00021"}
    assert session.calls[0][2] == [[21]]


async def test_read_record_of_a_missing_id_is_not_found():
    session = FakeSession({("sale.order", "read"): []})

    with pytest.raises(RecordNotFound):
        await tools(session).read_record("sale.order", 999)


@pytest.mark.parametrize("record_id", [0, -3, True])
async def test_read_record_rejects_invalid_ids(record_id):
    session = FakeSession()

    with pytest.raises(InvalidRequest):
        await tools(session).read_record("sale.order", record_id)
    assert session.calls == []


# --- list_models, describe_model, my_permissions ------------------------------------------


NOT_INSTALLED = InvalidRequest("Object crm.lead doesn't exist")  # what Odoo 18 really answers


async def test_list_models_shows_only_installed_allowed_models_the_user_can_read():
    # Regular users cannot read ir.model in Odoo, so each allowed model is probed directly.
    session = FakeSession(
        {
            ("crm.lead", "has_access"): NOT_INSTALLED,
            ("res.partner", "has_access"): True,
            ("sale.order", "has_access"): False,
        }
    )

    result = await tools(session, allowed_models=frozenset({*ALLOWED, "crm.lead"})).list_models()

    assert result["models"] == [{"model": "res.partner", "name": "Contacts"}]
    assert all(model != "ir.model" for model, *_ in session.calls)


async def test_describe_model_lists_fields_sorted_with_short_help():
    session = FakeSession(
        {
            ("sale.order", "fields_get"): {
                "state": {
                    "string": "Status",
                    "type": "selection",
                    "selection": [["draft", "Quotation"]],
                },
                "amount_total": {"string": "Total", "type": "monetary", "help": "h" * 900},
            }
        }
    )

    result = await tools(session).describe_model("sale.order")

    names = [f["name"] for f in result["fields"]]
    assert names == ["amount_total", "state"]
    assert len(result["fields"][0]["help"]) <= 310


async def test_my_permissions_reports_the_user_groups_and_rights_per_model():
    def has_access(args, kwargs):
        return args[1] == "read"

    session = FakeSession(
        {
            ("res.users", "read"): [
                {"id": 8, "name": "Ana (Sales)", "login": "ana", "groups_id": [1, 2]}
            ],
            ("res.groups", "read"): [
                {"id": 2, "full_name": "Sales / User"},
                {"id": 1, "full_name": "Internal User"},
            ],
            ("crm.lead", "has_access"): NOT_INSTALLED,
            ("res.partner", "has_access"): has_access,
            ("sale.order", "has_access"): has_access,
        }
    )

    result = await tools(session, allowed_models=frozenset({*ALLOWED, "crm.lead"})).my_permissions()

    assert "crm.lead" not in result["models"]

    assert result["user"] == {"id": 8, "name": "Ana (Sales)", "login": "ana"}
    assert result["groups"] == ["Internal User", "Sales / User"]
    assert result["models"]["sale.order"] == {
        "read": True,
        "create": False,
        "write": False,
        "unlink": False,
    }


# --- summarize_data ------------------------------------------------------------------------


async def test_summarize_groups_with_aggregates_and_hides_odoo_internals():
    groups = [
        {
            "user_id": [8, "Ana (Sales)"],
            "amount_total": 700.0,
            "__count": 2,
            "__domain": [["x", "=", 1]],
        },
    ]
    session = FakeSession({("sale.order", "read_group"): groups})

    result = await tools(session).summarize_data(
        "sale.order", group_by=["user_id"], aggregates=["amount_total:sum"]
    )

    model, method, args, kwargs = session.calls[0]
    assert args == [[], ["amount_total:sum"], ["user_id"]]
    assert kwargs["lazy"] is False
    assert result["groups"] == [{"user_id": [8, "Ana (Sales)"], "amount_total": 700.0, "count": 2}]


@pytest.mark.parametrize(
    ("group_by", "aggregates"),
    [
        ([], None),  # nothing to group by
        (["date_order:fortnight"], None),  # unknown granularity
        (["partner_id.country_id"], None),  # dotted path
        (["user_id"], ["amount_total:median"]),  # unknown aggregate
        (["user_id"], ["amount_total"]),  # aggregate without function
        (["a", "b", "c"], None),  # too many levels
    ],
)
async def test_summarize_rejects_invalid_grouping(group_by, aggregates):
    session = FakeSession()

    with pytest.raises(InvalidRequest):
        await tools(session).summarize_data("sale.order", group_by=group_by, aggregates=aggregates)
    assert session.calls == []


async def test_summarize_accepts_a_date_granularity():
    session = FakeSession({("sale.order", "read_group"): []})

    await tools(session).summarize_data("sale.order", group_by=["date_order:month"])

    assert session.calls[0][2][2] == ["date_order:month"]
