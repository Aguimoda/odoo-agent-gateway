import json

import pytest

from odoo_agent_gateway.audit import (
    AuditEvent,
    AuditUnavailable,
    MemoryAuditSink,
    audit_arguments,
)

pytestmark = pytest.mark.anyio


def event(**changes) -> AuditEvent:
    values = dict(
        request_id="1",
        login="ana",
        odoo_uid=8,
        tool="search_records",
        arguments={"model": "sale.order"},
        outcome="ok",
        result_count=2,
        duration_ms=12,
    )
    values.update(changes)
    return AuditEvent(**values)


def test_small_arguments_are_kept_as_they_are():
    arguments = {"model": "sale.order", "domain": [["state", "=", "sale"]], "limit": 5}

    assert audit_arguments(arguments) == arguments


def test_large_arguments_are_cut_but_stay_valid_json():
    arguments = {"model": "res.partner", "domain": [["name", "ilike", "x" * 10_000]]}

    stored = audit_arguments(arguments)

    assert stored["truncated"] is True
    assert len(stored["preview"]) == 4000
    json.dumps(stored)  # still serialisable for the jsonb column


def test_values_that_are_not_json_are_stored_as_text():
    class Odd:
        def __str__(self) -> str:
            return "odd-value"

    assert audit_arguments({"value": Odd()}) == {"value": "odd-value"}


async def test_memory_sink_keeps_events_in_order():
    sink = MemoryAuditSink()

    await sink.record(event(tool="list_models"))
    await sink.record(event(tool="read_record"))

    assert [e.tool for e in sink.events] == ["list_models", "read_record"]


async def test_memory_sink_can_simulate_an_outage():
    sink = MemoryAuditSink(available=False)

    with pytest.raises(AuditUnavailable):
        await sink.record(event())
    assert sink.events == []


def test_audit_unavailable_has_its_own_error_code():
    assert AuditUnavailable("x").code == "audit_unavailable"
