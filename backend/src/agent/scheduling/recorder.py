"""Action validation, normalization and the per-call action queue.

Normalization mirrors ``docs/prosper/normalization.md`` exactly where a human
voice was in the loop (the demographics a REGISTER captures and the moment of
an appointment). Ids, routes and timestamps the API returned are never
reshaped.

``ActionRecorder`` is the per-socket queue: one instance per call, no state
shared between calls. It validates an action when it is recorded (so a data
bug surfaces before the 30-second flush window) and can flush a bounded,
deadline-aware set of submissions at the end of the call.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}
_NATIONAL_ID_CLEAN = re.compile(r"[\s-]+")
INSURERS = frozenset({
    "sanitas", "adeslas", "dkv", "asisa", "mapfre", "caser", "cigna", "axa",
    "nueva_mutua", "privado",
})

# The exact body each submit route accepts, besides ``call_id``. Order is the
# contract's order; a route that is not here cannot be submitted.
ROUTE_FIELDS: dict[str, tuple[str, ...]] = {
    "register": (
        "given_name",
        "first_surname",
        "second_surname",
        "national_id",
        "date_of_birth",
        "phone",
        "email",
        "insurer",
    ),
    "book": (
        "patient_id",
        "provider_id",
        "location_id",
        "appointment_type_id",
        "slot",
        "policy_id",
    ),
    "reschedule": ("appointment_id", "provider_id", "location_id", "slot", "policy_id"),
    "cancel": ("appointment_id",),
    "no-action": ("reason",),
    "escalate": ("reason",),
}

ACTION_VERBS = {
    "register": "REGISTER",
    "book": "BOOK",
    "reschedule": "RESCHEDULE",
    "cancel": "CANCEL",
    "no-action": "NO_ACTION",
    "escalate": "ESCALATE",
}


def validate_national_id(raw: str) -> str:
    """Normalize a DNI/NIE and re-derive its check letter.

    Internal whitespace and hyphens are stripped, the value is uppercased and
    the letter is recomputed from the digits. Raises ``ValueError`` on a
    malformed shape or a mismatching check letter.
    """
    text = _NATIONAL_ID_CLEAN.sub("", str(raw or "")).upper()
    if not text:
        raise ValueError("empty national id")
    if text[0] in _NIE_PREFIX:
        prefix, digits, letter = text[0], text[1:-1], text[-1]
        if len(digits) != 7 or not digits.isdigit() or not letter.isalpha():
            raise ValueError(f"bad NIE shape: {raw!r}")
        number = int(_NIE_PREFIX[prefix] + digits)
        normalized = prefix + digits + letter
    else:
        digits, letter = text[:-1], text[-1]
        if len(digits) != 8 or not digits.isdigit() or not letter.isalpha():
            raise ValueError(f"bad DNI shape: {raw!r}")
        number = int(digits)
        normalized = digits + letter
    expected = _DNI_LETTERS[number % 23]
    if letter != expected:
        raise ValueError(f"check letter {letter!r} does not match digits (expected {expected!r})")
    return normalized


def normalize_phone(raw: str) -> str:
    """Fold ``+34 612 345 678`` / ``0034-612-345-678`` to nine national digits."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return ""
    if digits.startswith("0034") and len(digits) >= 13:
        digits = digits[4:]
    elif digits.startswith("34") and len(digits) == 11:
        digits = digits[2:]
    return digits


def normalize_email(raw: str) -> str:
    """Strip *all* whitespace and case-fold, per the normalization table."""
    email = re.sub(r"\s+", "", str(raw or "")).lower()
    if email.count("@") != 1:
        raise ValueError(f"bad email: {raw!r}")
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        raise ValueError(f"bad email: {raw!r}")
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
        raise ValueError(f"bad email: {raw!r}")
    return email


def normalize_slot(raw: str) -> str:
    """Truncate seconds and express the instant in Europe/Madrid.

    ``2026-09-19T08:30:00+00:00`` and ``2026-09-19T10:30:07+02:00`` both become
    ``2026-09-19T10:30:00+02:00``. A naive value is read as Madrid wall time.
    """
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty slot")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"bad slot: {raw!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MADRID)
    madrid = parsed.astimezone(MADRID).replace(microsecond=0, second=0)
    return madrid.isoformat(timespec="seconds")


def normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    """Apply normalization to a queued action before submission."""
    route = action.get("route")
    out = dict(action)
    if route == "register":
        out["national_id"] = validate_national_id(action.get("national_id", ""))
        out["phone"] = normalize_phone(action.get("phone", ""))
        out["email"] = normalize_email(action.get("email", ""))
        for key in ("given_name", "first_surname", "second_surname", "date_of_birth", "insurer"):
            out[key] = str(action.get(key) or "").strip()
        out["insurer"] = re.sub(r"[\s-]+", "_", out["insurer"].casefold())
        if out["insurer"] not in INSURERS:
            raise ValueError("insurer: ask for a supported insurance plan or privado")
        try:
            birthday = date.fromisoformat(out["date_of_birth"])
        except ValueError as exc:
            raise ValueError("date_of_birth: ask for the full date (YYYY-MM-DD)") from exc
        if birthday > datetime.now(MADRID).date():
            raise ValueError("date_of_birth: cannot be in the future; ask again")
        out["date_of_birth"] = birthday.isoformat()
        for key in ROUTE_FIELDS["register"]:
            value = str(out.get(key, "")).casefold()
            if value in {"unknown", "n/a", "none", "pending", "not provided"} or any(
                marker in value for marker in ("placeholder", "replace_me", "example.com")
            ):
                raise ValueError(f"{key}: missing caller data; ask for it, never use a placeholder")
    if route in ("book", "reschedule") and action.get("slot"):
        out["slot"] = normalize_slot(action["slot"])
    if route in ("no-action", "escalate"):
        out["reason"] = str(action.get("reason") or "").strip().lower()
    return out


def build_body(action: dict[str, Any], call_id: str) -> dict[str, Any]:
    """Return the exact JSON body for one submit route, or raise ``ValueError``.

    The body is ``call_id`` plus exactly the fields that route carries; extra
    keys in ``action`` are dropped so a stray key can never cause a 422.
    """
    route = str(action.get("route", ""))
    fields = ROUTE_FIELDS.get(route)
    if fields is None:
        raise ValueError(f"unknown action route: {route!r}")
    normalized = normalize_action(action)
    missing = [name for name in fields if normalized.get(name) in (None, "")]
    if missing:
        raise ValueError(f"{route}: missing required field(s): {', '.join(missing)}")
    body: dict[str, Any] = {"call_id": call_id}
    body.update({name: normalized[name] for name in fields})
    return body


@dataclass(frozen=True)
class QueuedAction:
    """One validated action waiting for the end-of-call flush."""

    route: str
    action: dict[str, Any]
    body: dict[str, Any]

    @property
    def verb(self) -> str:
        return ACTION_VERBS.get(self.route, self.route.upper())


@dataclass
class FlushReport:
    """Tally of a recorder flush, by submission outcome."""

    accepted: int = 0
    duplicates: int = 0
    terminal: int = 0
    data_bugs: int = 0
    failed: int = 0
    skipped: int = 0
    outcomes: list[Any] = field(default_factory=list)

    @property
    def settled(self) -> int:
        return self.accepted + self.duplicates + self.terminal + self.data_bugs

    @property
    def complete(self) -> bool:
        return self.failed == 0 and self.skipped == 0

    def add(self, outcome: Any) -> None:
        self.outcomes.append(outcome)
        status = getattr(outcome, "status", "failed")
        if status == "accepted":
            self.accepted += 1
        elif status == "duplicate":
            self.duplicates += 1
        elif status == "terminal":
            self.terminal += 1
        elif status == "data_bug":
            self.data_bugs += 1
        elif status == "skipped":
            self.skipped += 1
        else:
            self.failed += 1


class ActionRecorder:
    """Per-call action queue. One recorder per socket, never shared."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self._actions: list[QueuedAction] = []

    def __len__(self) -> int:
        return len(self._actions)

    @property
    def actions(self) -> list[QueuedAction]:
        return list(self._actions)

    def record(self, action: dict[str, Any]) -> QueuedAction:
        """Validate + normalize ``action`` and append it to the queue."""
        route = str(action.get("route", ""))
        body = build_body(action, self.call_id)
        queued = QueuedAction(route=route, action=dict(action), body=body)
        self._actions.append(queued)
        return queued

    add = record

    async def flush(
        self,
        submitter: Any,
        *,
        deadline: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> FlushReport:
        """Submit every queued action in order, never past ``deadline``.

        ``deadline`` is a :func:`time.monotonic` instant. It is passed to the
        submitter as well, so an in-flight retry cannot cross it either.
        """
        report = FlushReport()
        for index, queued in enumerate(self._actions):
            if deadline is not None and clock() >= deadline:
                report.skipped = len(self._actions) - index
                break
            outcome = await submitter.submit(queued.action, self.call_id, deadline=deadline)
            report.add(outcome)
        return report
