from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import pytest

from odoo_agent_gateway.odoo import AccessDenied, InvalidRequest, RecordNotFound
from odoo_agent_gateway.proposal_store import Proposal
from odoo_agent_gateway.proposals import Conflict, FourEyes, ProposalService
from odoo_agent_gateway.tools import Limits

pytestmark = pytest.mark.anyio

ANA, LUIS, EVA = 8, 9, 10
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)

FIELDS = {
    "res.partner": {
        "phone": {"type": "char", "readonly": False},
        "comment": {"type": "html", "readonly": False},
        "active": {"type": "boolean", "readonly": False},
        "child_ids": {"type": "one2many", "readonly": False},
        "display_name": {"type": "char", "readonly": True},
        "customer_rank": {"type": "integer", "readonly": False},
        "country_id": {"type": "many2one", "readonly": False},
        "lang": {
            "type": "selection",
            "readonly": False,
            "selection": [["en_US", "English"], ["es_ES", "Spanish"]],
        },
        "birthday": {"type": "date", "readonly": False},
    }
}


class World:
    """A tiny Odoo: records, who can read or write them, and every write that happened."""

    def __init__(self) -> None:
        self.records = {
            ("res.partner", 5): {
                "phone": "+34 911 000 000",
                "comment": False,
                "country_id": [68, "Spain"],
                "lang": "es_ES",
            }
        }
        self.readers = {ANA: {("res.partner", 5)}, LUIS: {("res.partner", 5)}, EVA: set()}
        self.writers = {ANA: set(), LUIS: {("res.partner", 5)}, EVA: set()}
        self.invalid_values: set[Any] = set()
        self.writes: list[tuple[int, str, int, dict]] = []


class Session:
    def __init__(self, world: World, uid: int, login: str) -> None:
        self.world, self.uid, self.login = world, uid, login

    async def call(self, model, method, args=None, kwargs=None):
        args, kwargs = args or [], kwargs or {}
        world = self.world
        if method == "fields_get":
            return FIELDS[model]
        if method == "search":
            ((field, op, value),) = args[0]
            ids = value if op == "in" else [value]
            return [
                i
                for i in ids
                if (model, i) in world.readers[self.uid] and (model, i) in world.records
            ]
        if method == "read":
            (ids, fields) = args
            for i in ids:
                if (model, i) not in world.readers[self.uid]:
                    raise AccessDenied("denied")
                if (model, i) not in world.records:
                    raise RecordNotFound("gone")
            return [
                {"id": i, **{f: world.records[(model, i)].get(f, False) for f in fields}}
                for i in ids
            ]
        if method == "write":
            (ids, values) = args
            for i in ids:
                if (model, i) not in world.writers[self.uid]:
                    raise AccessDenied("denied")
            if any(v in world.invalid_values for v in values.values()):
                raise InvalidRequest("Odoo says: invalid value")
            for i in ids:
                world.records[(model, i)].update(values)
                world.writes.append((self.uid, model, i, values))
            return True
        raise AssertionError(f"unexpected {model}.{method}")


class MemoryStore:
    def __init__(self, clock) -> None:
        self.items: dict[int, Proposal] = {}
        self.ids = count(1)
        self.clock = clock

    async def create(self, **values):
        proposal = Proposal(id=next(self.ids), created_at=self.clock(), **values)
        self.items[proposal.id] = proposal
        return proposal

    async def get(self, proposal_id):
        return self.items.get(proposal_id)

    async def list_by_proposer(self, uid, status, limit):
        found = [
            p for p in self.items.values() if p.proposer_uid == uid and status in (None, p.status)
        ]
        return found[:limit]

    async def list_pending(self, limit):
        return [p for p in self.items.values() if p.status == "pending"][:limit]

    async def decide(self, proposal_id, decider, *, decider_login, decider_uid, note):
        proposal = self.items.get(proposal_id)
        if proposal is None:
            raise RecordNotFound("no proposal")
        decision = await decider(proposal)
        if decision is None:
            return proposal
        from dataclasses import replace

        decided = replace(
            proposal,
            status=decision.status,
            error_code=decision.error_code,
            decided_at=self.clock(),
            decider_login=decider_login,
            decider_uid=decider_uid,
            decision_note=note,
        )
        self.items[proposal_id] = decided
        return decided


@pytest.fixture
def world():
    return World()


@pytest.fixture
def clock():
    state = {"now": NOW}

    def now():
        return state["now"]

    now.state = state
    return now


@pytest.fixture
def service(clock):
    return ProposalService(
        MemoryStore(clock), Limits(allowed_models=frozenset({"res.partner"})), clock=clock
    )


def ana(world):
    return Session(world, ANA, "ana")


def luis(world):
    return Session(world, LUIS, "luis")


def eva(world):
    return Session(world, EVA, "eva")


REASON = "The customer called to give us a new phone number."


async def propose(service, world, values=None, **kwargs):
    return await service.propose(
        ana(world),
        kwargs.get("model", "res.partner"),
        kwargs.get("record_id", 5),
        values if values is not None else {"phone": "+34 600 111 222"},
        kwargs.get("reason", REASON),
    )


# --- proposing -----------------------------------------------------------------------------


async def test_a_proposal_is_stored_and_nothing_changes_in_odoo(service, world):
    result = await propose(service, world)

    assert result["status"] == "pending"
    assert result["changes"] == {"phone": "+34 600 111 222"}
    assert "Nothing has changed" in result["notice"]
    assert world.writes == []
    assert world.records[("res.partner", 5)]["phone"] == "+34 911 000 000"


@pytest.mark.parametrize(
    "values",
    [
        {},  # nothing to change
        {f"f{i}": "x" for i in range(11)},  # too many fields
        {"active": False},  # archiving is not offered
        {"state": "cancel"},  # workflow states are not offered
        {"company_id": 2},
        {"child_ids": [1, 2]},  # x2many lists
        {"display_name": "New"},  # read-only
        {"nope": "x"},  # unknown field
        {"lang": "xx_XX"},  # not an allowed selection value
        {"country_id": "Spain"},  # many2one needs an id
        {"customer_rank": "ten"},  # integer needs a number
        {"birthday": "23/11/2026"},  # dates are YYYY-MM-DD
        {"phone": "x" * 2001},  # oversized text
        {"partner_id.name": "x"},  # dotted path
    ],
)
async def test_invalid_changes_are_refused_and_not_stored(service, world, values):
    with pytest.raises(InvalidRequest):
        await propose(service, world, values)

    assert await service._store.list_pending(10) == []


@pytest.mark.parametrize("reason", ["", "short", "x" * 501, None])
async def test_a_reason_of_10_to_500_characters_is_required(service, world, reason):
    with pytest.raises(InvalidRequest):
        await propose(service, world, reason=reason)


async def test_models_outside_the_allowlist_are_refused(service, world):
    with pytest.raises(InvalidRequest):
        await propose(service, world, model="hr.employee")


async def test_nobody_proposes_changes_to_records_they_cannot_see(service, world):
    world.readers[ANA].clear()

    with pytest.raises(AccessDenied):
        await propose(service, world)


async def test_valid_simple_types_are_accepted(service, world):
    values = {
        "lang": "en_US",
        "country_id": 1,
        "customer_rank": 3,
        "birthday": "1990-05-01",
        "comment": "<p>Prefers mornings</p>",
        "phone": False,
    }

    result = await propose(service, world, values)

    assert result["changes"] == values


# --- approving -----------------------------------------------------------------------------


async def test_a_different_person_approves_and_the_write_runs_as_them(service, world):
    proposal_id = (await propose(service, world))["proposal_id"]

    result = await service.approve(luis(world), proposal_id, "Checked with the customer.")

    assert result["status"] == "applied"
    assert result["decided_by"] == "luis"
    assert world.writes == [(LUIS, "res.partner", 5, {"phone": "+34 600 111 222"})]


async def test_nobody_approves_their_own_proposal(service, world):
    world.writers[ANA].add(("res.partner", 5))
    proposal_id = (await propose(service, world))["proposal_id"]

    with pytest.raises(FourEyes):
        await service.approve(ana(world), proposal_id, None)
    assert world.writes == []
    assert (await service._store.get(proposal_id)).status == "pending"


async def test_an_approver_who_cannot_see_the_record_is_refused(service, world):
    proposal_id = (await propose(service, world))["proposal_id"]

    with pytest.raises(AccessDenied):
        await service.approve(eva(world), proposal_id, None)
    assert world.writes == []
    assert (await service._store.get(proposal_id)).status == "pending"


async def test_an_approver_without_write_rights_leaves_it_pending_for_someone_else(service, world):
    world.readers[EVA].add(("res.partner", 5))
    proposal_id = (await propose(service, world))["proposal_id"]

    with pytest.raises(AccessDenied):
        await service.approve(eva(world), proposal_id, None)
    assert (await service._store.get(proposal_id)).status == "pending"
    assert (await service.approve(luis(world), proposal_id, None))["status"] == "applied"


async def test_a_record_changed_since_the_proposal_is_a_conflict(service, world):
    proposal_id = (await propose(service, world))["proposal_id"]
    world.records[("res.partner", 5)]["phone"] = "+34 999 999 999"  # someone edited it meanwhile

    result = await service.approve(luis(world), proposal_id, None)

    assert result["status"] == "conflict"
    assert world.writes == []


async def test_odoo_business_rules_can_make_a_proposal_fail(service, world):
    world.invalid_values.add("+34 600 111 222")
    proposal_id = (await propose(service, world))["proposal_id"]

    result = await service.approve(luis(world), proposal_id, None)

    assert (result["status"], result["error_code"]) == ("failed", "invalid_request")


async def test_a_decided_proposal_cannot_be_decided_again(service, world):
    proposal_id = (await propose(service, world))["proposal_id"]
    await service.approve(luis(world), proposal_id, None)

    with pytest.raises(Conflict):
        await service.approve(luis(world), proposal_id, None)
    with pytest.raises(Conflict):
        await service.reject(luis(world), proposal_id, "too late")
    assert len(world.writes) == 1


async def test_proposals_expire_after_seven_days(service, world, clock):
    proposal_id = (await propose(service, world))["proposal_id"]
    clock.state["now"] = NOW + timedelta(days=7, minutes=1)

    result = await service.approve(luis(world), proposal_id, None)

    assert result["status"] == "expired"
    assert world.writes == []


async def test_an_unknown_proposal_is_not_found(service, world):
    with pytest.raises(RecordNotFound):
        await service.approve(luis(world), 999, None)


@pytest.mark.parametrize("proposal_id", [0, -1, True, "1"])
async def test_proposal_ids_must_be_positive_integers(service, world, proposal_id):
    with pytest.raises(InvalidRequest):
        await service.approve(luis(world), proposal_id, None)


# --- rejecting -----------------------------------------------------------------------------


async def test_an_approver_can_reject_with_a_note(service, world):
    proposal_id = (await propose(service, world))["proposal_id"]

    result = await service.reject(luis(world), proposal_id, "Wrong number, call back.")

    assert (result["status"], result["decision_note"]) == ("rejected", "Wrong number, call back.")
    assert world.writes == []


async def test_proposers_can_withdraw_their_own_proposal(service, world):
    proposal_id = (await propose(service, world))["proposal_id"]

    result = await service.reject(ana(world), proposal_id, "Sent by mistake.")

    assert result["status"] == "rejected"


async def test_people_who_cannot_see_the_record_cannot_reject_it(service, world):
    proposal_id = (await propose(service, world))["proposal_id"]

    with pytest.raises(AccessDenied):
        await service.reject(eva(world), proposal_id, "No.")


# --- listings ------------------------------------------------------------------------------


async def test_people_list_only_their_own_proposals(service, world):
    await propose(service, world)

    assert len((await service.list_mine(ana(world)))["proposals"]) == 1
    assert (await service.list_mine(luis(world)))["proposals"] == []


async def test_status_filters_are_validated(service, world):
    with pytest.raises(InvalidRequest):
        await service.list_mine(ana(world), status="maybe")


async def test_pending_lists_show_others_proposals_on_readable_records_with_current_values(
    service, world
):
    proposal_id = (await propose(service, world))["proposal_id"]

    for_luis = (await service.pending_for(luis(world)))["proposals"]
    for_ana = (await service.pending_for(ana(world)))["proposals"]
    for_eva = (await service.pending_for(eva(world)))["proposals"]

    assert [p["proposal_id"] for p in for_luis] == [proposal_id]
    assert for_luis[0]["current"] == {"phone": "+34 911 000 000"}
    assert for_ana == []  # her own proposal: she cannot approve it
    assert for_eva == []  # she cannot see the record
