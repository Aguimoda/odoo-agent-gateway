"""Write proposals with four-eyes approval (ADR 0012).

The agent can only propose. A different person approves, and the write then runs in Odoo
with that person's own credentials, so Odoo checks their rights at that moment.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from odoo_agent_gateway.odoo import AccessDenied, InvalidRequest, OdooError, RecordNotFound
from odoo_agent_gateway.proposal_store import Decision, Proposal
from odoo_agent_gateway.tools import Limits, Session

MAX_FIELDS = 10
MAX_TEXT = 2000
REASON_LENGTH = (10, 500)
NOTE_LIMIT = 500
EXPIRY = timedelta(days=7)
STATUSES = ("pending", "applied", "rejected", "conflict", "failed", "expired")
ALLOWED_TYPES = frozenset(
    {
        "char",
        "text",
        "html",
        "integer",
        "float",
        "monetary",
        "boolean",
        "date",
        "datetime",
        "selection",
        "many2one",
    }
)
FORBIDDEN_FIELDS = frozenset(
    {
        "active",
        "state",
        "company_id",
        "id",
        "display_name",
        "create_uid",
        "create_date",
        "write_uid",
        "write_date",
    }
)
PROPOSAL_NOTICE = (
    "Nothing has changed in Odoo yet. A different person must approve this proposal; "
    "the change then runs with their rights."
)

_FIELD = re.compile(r"^[a-z_][a-z0-9_]*$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class FourEyes(OdooError):
    code = "four_eyes"


class Conflict(OdooError):
    code = "conflict"


def fingerprint(row: dict[str, Any], fields: list[str]) -> str:
    """SHA-256 of the current values of `fields`; many2one pairs are reduced to their id."""
    values = {}
    for name in sorted(fields):
        value = row.get(name, False)
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
            value = value[0]
        values[name] = value
    text = json.dumps(values, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {name: row.get(name, False) for name in fields}


class ProposalService:
    def __init__(
        self,
        store: Any,
        limits: Limits,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        expiry: timedelta = EXPIRY,
    ) -> None:
        self._store = store
        self._limits = limits
        self._clock = clock
        self._expiry = expiry

    # -- proposing (MCP tools) --------------------------------------------------------------

    async def propose(
        self, session: Session, model: Any, record_id: Any, values: Any, reason: Any
    ) -> dict[str, Any]:
        self._check_model(model)
        record_id = self._check_id(record_id, "record_id")
        reason = self._check_reason(reason)
        changes = self._check_shape(values)

        specs = await session.call(
            model, "fields_get", [], {"attributes": ["type", "readonly", "selection"]}
        )
        changes = {
            name: self._check_value(name, value, specs.get(name)) for name, value in changes.items()
        }

        if not await session.call(model, "search", [[["id", "=", record_id]]]):
            raise AccessDenied("You cannot see this record, so you cannot propose changes to it.")
        rows = await session.call(model, "read", [[record_id], sorted(changes)])
        proposal = await self._store.create(
            proposer_login=session.login,
            proposer_uid=session.uid,
            model=model,
            record_id=record_id,
            changes=changes,
            before_hash=fingerprint(rows[0], sorted(changes)),
            reason=reason,
        )
        return {**proposal.public(), "notice": PROPOSAL_NOTICE}

    async def list_mine(
        self, session: Session, status: Any = None, limit: Any = None
    ) -> dict[str, Any]:
        if status is not None and status not in STATUSES:
            raise InvalidRequest(f"status must be one of: {', '.join(STATUSES)}.")
        limit = self._check_limit(limit)
        proposals = await self._store.list_by_proposer(session.uid, status, limit)
        return {"proposals": [proposal.public() for proposal in proposals]}

    # -- deciding (approval API, never an MCP tool) -----------------------------------------

    async def pending_for(self, session: Session, limit: Any = None) -> dict[str, Any]:
        """Pending proposals by others, on records this approver can read, with live values."""
        limit = self._check_limit(limit)
        pending = await self._store.list_pending(
            200, models=self._limits.allowed_models, exclude_proposer_uid=session.uid
        )
        candidates = [
            proposal
            for proposal in pending
            if proposal.proposer_uid != session.uid
            and proposal.model in self._limits.allowed_models
        ]
        by_model: dict[str, list[Proposal]] = defaultdict(list)
        for proposal in candidates:
            by_model[proposal.model].append(proposal)

        visible: set[tuple[str, int]] = set()
        for model, proposals in by_model.items():
            ids = sorted({p.record_id for p in proposals})
            for record_id in await session.call(model, "search", [[["id", "in", ids]]]):
                visible.add((model, record_id))

        result = []
        for proposal in candidates:
            if len(result) >= limit:
                break
            if (proposal.model, proposal.record_id) not in visible:
                continue
            fields = sorted(proposal.changes)
            try:
                rows = await session.call(proposal.model, "read", [[proposal.record_id], fields])
            except (AccessDenied, RecordNotFound):
                continue
            result.append({**proposal.public(), "current": _current(rows[0], fields)})
        return {"proposals": result}

    async def approve(self, session: Session, proposal_id: Any, note: Any) -> dict[str, Any]:
        proposal_id = self._check_id(proposal_id, "proposal_id")
        note = self._check_note(note)

        async def decide(proposal: Proposal) -> Decision | None:
            self._check_pending(proposal)
            if proposal.proposer_uid == session.uid:
                raise FourEyes("You cannot approve your own proposal: another person must.")
            self._check_model(proposal.model)
            if self._clock() - proposal.created_at > self._expiry:
                return Decision("expired")
            fields = sorted(proposal.changes)
            try:  # AccessDenied propagates: the proposal stays pending for someone else
                rows = await session.call(proposal.model, "read", [[proposal.record_id], fields])
            except RecordNotFound:
                return Decision("failed", RecordNotFound.code)
            if not rows:
                return Decision("failed", RecordNotFound.code)
            if fingerprint(rows[0], fields) != proposal.before_hash:
                return Decision("conflict")
            try:
                await session.call(
                    proposal.model, "write", [[proposal.record_id], proposal.changes]
                )
            except (InvalidRequest, RecordNotFound) as error:
                return Decision("failed", error.code)
            return Decision("applied")

        decided = await self._store.decide(
            proposal_id, decide, decider_login=session.login, decider_uid=session.uid, note=note
        )
        return decided.public()

    async def reject(self, session: Session, proposal_id: Any, note: Any) -> dict[str, Any]:
        """Approvers reject; proposers may withdraw their own proposal."""
        proposal_id = self._check_id(proposal_id, "proposal_id")
        note = self._check_note(note)

        async def decide(proposal: Proposal) -> Decision:
            self._check_pending(proposal)
            if proposal.proposer_uid != session.uid:
                visible = await session.call(
                    proposal.model, "search", [[["id", "=", proposal.record_id]]]
                )
                if not visible:
                    raise AccessDenied("You cannot see the record this proposal changes.")
            return Decision("rejected")

        decided = await self._store.decide(
            proposal_id, decide, decider_login=session.login, decider_uid=session.uid, note=note
        )
        return decided.public()

    # -- validation -------------------------------------------------------------------------

    def _check_model(self, model: Any) -> None:
        if not isinstance(model, str) or model not in self._limits.allowed_models:
            allowed = ", ".join(sorted(self._limits.allowed_models))
            raise InvalidRequest(
                f"Model '{model}' is not exposed by this gateway. Allowed: {allowed}."
            )

    @staticmethod
    def _check_id(value: Any, name: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise InvalidRequest(f"{name} must be a positive integer.")
        return value

    @staticmethod
    def _check_reason(reason: Any) -> str:
        low, high = REASON_LENGTH
        if not isinstance(reason, str) or not low <= len(reason.strip()) <= high:
            raise InvalidRequest(f"reason must explain the change in {low} to {high} characters.")
        return reason.strip()

    @staticmethod
    def _check_note(note: Any) -> str | None:
        if note is None:
            return None
        if not isinstance(note, str) or len(note) > NOTE_LIMIT:
            raise InvalidRequest(f"note must be text of at most {NOTE_LIMIT} characters.")
        return note.strip() or None

    @staticmethod
    def _check_limit(limit: Any) -> int:
        if limit is None:
            return 20
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise InvalidRequest("limit must be between 1 and 50.")
        return limit

    @staticmethod
    def _check_pending(proposal: Proposal) -> None:
        if proposal.status != "pending":
            raise Conflict(f"Proposal {proposal.id} is already {proposal.status}.")

    @staticmethod
    def _check_shape(values: Any) -> dict[str, Any]:
        if not isinstance(values, dict) or not values:
            raise InvalidRequest("values must name at least one field to change.")
        if len(values) > MAX_FIELDS:
            raise InvalidRequest(f"At most {MAX_FIELDS} fields per proposal.")
        for name in values:
            if not isinstance(name, str) or not _FIELD.match(name):
                raise InvalidRequest(f"'{name}' is not a plain field name.")
            if name in FORBIDDEN_FIELDS:
                raise InvalidRequest(f"Field '{name}' cannot be changed through proposals.")
        return dict(values)

    @staticmethod
    def _check_value(name: str, value: Any, spec: dict[str, Any] | None) -> Any:
        if spec is None:
            raise InvalidRequest(f"Field '{name}' does not exist on this model.")
        kind = spec.get("type")
        if spec.get("readonly") or kind not in ALLOWED_TYPES:
            raise InvalidRequest(f"Field '{name}' ({kind}) cannot be changed through proposals.")
        if value is None or (value is False and kind != "boolean"):
            return False  # Odoo's way to clear a field
        valid = {
            "char": lambda v: isinstance(v, str) and len(v) <= MAX_TEXT,
            "text": lambda v: isinstance(v, str) and len(v) <= MAX_TEXT,
            "html": lambda v: isinstance(v, str) and len(v) <= MAX_TEXT,
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "monetary": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "date": lambda v: (
                isinstance(v, str) and bool(_DATE.match(v)) and _parses(date.fromisoformat, v)
            ),
            "datetime": lambda v: (
                isinstance(v, str)
                and bool(_DATETIME.match(v))
                and _parses(datetime.fromisoformat, v)
            ),
            "selection": lambda v: v in {key for key, _ in spec.get("selection") or []},
            "many2one": lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
        }[kind]
        if not valid(value):
            raise InvalidRequest(f"Value for '{name}' is not a valid {kind}.")
        return value


def _parses(parser: Callable[[str], Any], value: str) -> bool:
    try:
        parser(value)
    except ValueError:
        return False
    return True
