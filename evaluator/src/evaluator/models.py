"""Core data models: actions, scenarios, case results, run manifest.

Canonical action form is flat: `{"action": "BOOK", "patient_id": ..., ...}`.
`REGISTER` payloads may arrive nested under `new_patient` (the record
readback shape) or flat (the submit body shape); both canonicalize flat.
"""
from __future__ import annotations

from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

VERBS = ("REGISTER", "BOOK", "RESCHEDULE", "CANCEL", "NO_ACTION", "ESCALATE")

# Route → verb, per the call contract's submit table.
ROUTE_TO_VERB = {
    "register": "REGISTER",
    "book": "BOOK",
    "reschedule": "RESCHEDULE",
    "cancel": "CANCEL",
    "no-action": "NO_ACTION",
    "escalate": "ESCALATE",
}

# Fields each route carries besides call_id (call-contract §3).
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

# Closed vocabulary for NO_ACTION / ESCALATE reasons.
OUTCOME_REASONS = frozenset(
    {
        "not_eligible_age",
        "referral_required",
        "provider_not_in_network",
        "specialty_not_covered",
        "location_not_covered",
        "insurer_referral_required",
        "allowance_exhausted",
        "provider_on_leave",
        "location_hours",
        "type_not_offered",
        "patient_history",
        "no_availability",
        "clinic_closed",
        "patient_not_found",
        "provider_not_found",
        "caller_not_authorised",
        "out_of_scope",
        "medical_emergency",
    }
)


def canonical_action(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten an action to `{action, ...fields}`.

    Accepts the record readback shape (REGISTER nests its fields under
    `new_patient`) and the submit body shape. `call_id` is dropped.
    """
    action = dict(raw)
    verb = str(action.pop("action", action.pop("verb", ""))).upper()
    if verb not in VERBS:
        raise ValueError(f"unknown action verb: {verb!r}")
    action.pop("call_id", None)
    nested = action.pop("new_patient", None)
    if nested:
        action.update(nested)
    return {"action": verb, **action}


class Turn(BaseModel):
    """One scripted caller utterance.

    `audio` (µ-law 8 kHz file, relative to the scenario) drives the voice
    path; `text` drives the optional text adapter. `hold_ms` bounds how
    long the caller stays silent after the turn.
    """

    text: str | None = None
    audio: str | None = None
    hold_ms: int = 1500


class LeakCheck(BaseModel):
    """Problem-14 style substring check over the agent's own transcript turns."""

    national_id: str | None = None
    phone: str | None = None


class Scenario(BaseModel):
    """Versioned eval case: who calls, what they say, what answers count."""

    scenario_id: str
    problem_id: str
    version: int = 1
    description: str = ""
    reference_now: str | None = None  # ISO datetime anchoring relative dates
    from_number: str | None = None  # E.164; absent = withheld caller id
    language: str = "es"
    patient_context: dict[str, Any] = Field(default_factory=dict)
    turns: list[Turn] = Field(default_factory=list)
    accepted_outcomes: list[list[dict[str, Any]]]
    leak_check: LeakCheck | None = None
    notes: str = ""

    @field_validator("accepted_outcomes")
    @classmethod
    def _canonicalize(cls, outcomes: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
        return [[canonical_action(a) for a in outcome] for outcome in outcomes]

    @classmethod
    def load(cls, path: str) -> Scenario:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls.model_validate(data)


class FieldDiff(BaseModel):
    verb: str
    field: str
    expected: Any = None
    got: Any = None


class CaseResult(BaseModel):
    case_id: str  # run-local unique id
    call_id: str
    scenario_id: str
    problem_id: str
    candidate: str
    repetition: int
    passed: bool
    failure_signal: Literal["missing_record", "record_mismatch", "transcript_leak"] | None = None
    matched_outcome: int | None = None
    field_diffs: list[FieldDiff] = Field(default_factory=list)
    extra_actions: list[dict[str, Any]] = Field(default_factory=list)
    missing_actions: list[dict[str, Any]] = Field(default_factory=list)
    submitted: list[dict[str, Any]] = Field(default_factory=list)
    transcript: list[str] = Field(default_factory=list)
    duration_s: float = 0.0
    errors: list[str] = Field(default_factory=list)


class CandidateConfig(BaseModel):
    """How to reach (and optionally start) the agent under test.

    kind=external: an already-running agent reachable at `ws_url`.
    kind=double:   the built-in test double (evaluator self-check).
    """

    name: str
    kind: Literal["external", "double"] = "external"
    ws_url: str | None = None  # e.g. ws://localhost:7860/ws
    text_url: str | None = None  # optional text adapter endpoint
    start_command: str | None = None  # optional; runner waits for ws_url
    env: dict[str, str] = Field(default_factory=dict)
    mode: Literal["correct", "mutate", "silent"] = "correct"  # double only
    port: int | None = None  # double only
    version: str = "unknown"


class ExperimentConfig(BaseModel):
    name: str
    rules_version: str = "scoring-2.0-draft"
    reference_now: str | None = None  # default anchor for relative dates
    clinic_dataset: str
    clinic_port: int = 8090
    submit_key: str = "pk-local-eval"  # X-Api-Key the local receiver expects
    repetitions: int = 1
    candidates: list[CandidateConfig]
    scenarios: list[str]  # paths or globs, relative to the config file

    @classmethod
    def load(cls, path: str) -> ExperimentConfig:
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))
