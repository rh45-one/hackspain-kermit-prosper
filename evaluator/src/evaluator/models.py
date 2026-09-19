"""Core data models: actions, scenarios, case results, run manifest.

Canonical action form is flat: `{"action": "BOOK", "patient_id": ..., ...}`.
`REGISTER` payloads may arrive nested under `new_patient` (the record
readback shape) or flat (the submit body shape); both canonicalize flat.

Scenario schema follows the evaluator plan §8: `caller` (persona, facts,
behavior), `oracle` (accepted outcomes + extra checks) and `limits`.
"""
from __future__ import annotations

from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

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

# Problem weights from the plan §8 table (max 49 across the 17 scored
# families; switchboard is diagnostic-only and never scores).
PROBLEM_WEIGHTS: dict[str, int] = {
    "simple_booking": 1,
    "switchboard": 0,
    "doctor_and_site": 2,
    "new_patient": 2,
    "when_exactly": 2,
    "rules": 3,
    "no_slot_free": 2,
    "change_and_cancel": 2,
    "third_party": 3,
    "triage": 3,
    "languages": 3,
    "noise": 3,
    "difficult_caller": 4,
    "adversarial": 4,
    "nearest_site": 3,
    "questions": 3,
    "second_policy": 4,
    "real_call": 5,
}
MAX_LOCAL_POINTS = sum(PROBLEM_WEIGHTS.values())  # 49

# Failure-attribution categories from the plan §14.
DIAGNOSTIC_CATEGORIES = frozenset(
    {
        "stt_error",
        "identity_error",
        "reasoning_error",
        "tool_error",
        "state_error",
        "submission_error",
        "privacy_error",
        "transport_error",
        "provider_error",
        "harness_error",
        "unknown",
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


class NoiseSpec(BaseModel):
    """Noise texture mixed over a caller turn (plan §15: 5 dB, SNR vs speech).

    `file` is a µ-law 8 kHz asset relative to the scenario; `synth` asks the
    harness to generate deterministic noise locally when no asset exists.
    """

    file: str | None = None
    synth: str | None = None  # e.g. "brown" - local approximation, not official
    snr_db: float = 5.0


class Turn(BaseModel):
    """One scripted caller utterance for the voice (WS) path.

    `audio` (µ-law 8 kHz file, relative to the scenario) drives the voice
    path; `text` is the transcript of what the caller says. `hold_ms` bounds
    how long the caller stays silent after the turn.
    `interrupt_on_agent_audio` makes this utterance barge in as soon as the
    agent starts speaking (difficult-caller style interruption).
    """

    text: str | None = None
    audio: str | None = None
    hold_ms: int = 1500
    noise: NoiseSpec | None = None
    interrupt_on_agent_audio: bool = False
    tts: bool = False  # synthesise `text` via the configured TTS provider


class LeakCheck(BaseModel):
    """Problem-14 style substring check over the agent's own transcript turns."""

    national_id: str | None = None
    phone: str | None = None


class CallerBehavior(BaseModel):
    """How the simulated caller answers the agent (rules-based patient)."""

    provide_identifier_when_asked: bool = True
    accept_first_offer: bool = True
    accept_rescheduling: bool = True
    reveal_second_policy_when_asked: bool = False
    corrections: list[str] = Field(default_factory=list)
    max_repeats: int = 3  # unanswered turns before the caller gives up


class LLMConfig(BaseModel):
    """Optional LLM-driven caller (plan §11 second version).

    Restricted: the prompt carries persona + facts + behaviour rules only -
    never the oracle. Falls back to the rules patient on provider errors.
    """

    endpoint: str = "http://localhost:11434/v1/chat/completions"
    model: str = "qwen2.5:3b"
    key_env: str | None = None  # env var holding the API key, if any
    seed: int | None = None
    temperature: float = 0.4
    max_tokens: int = 120


class Caller(BaseModel):
    """Who calls and what they know - never the expected outcome.

    `opening` is the first utterance. `facts` holds everything the caller
    may truthfully reveal (name, ids, wishes). `behavior` tunes the rules.
    `llm` switches the simulated patient to the restricted-LLM version.
    """

    persona: str = "patient"
    from_number: str | None = None  # E.164; absent = withheld caller id
    opening: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    behavior: CallerBehavior = Field(default_factory=CallerBehavior)
    llm: LLMConfig | None = None


class Outcome(BaseModel):
    """One accepted alternative: the full action list must match it."""

    actions: list[dict[str, Any]]

    @field_validator("actions")
    @classmethod
    def _canonicalize(cls, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [canonical_action(a) for a in actions]


class Oracle(BaseModel):
    """What counts as correct - never shared with the agent under test."""

    accepted_outcomes: list[Outcome]
    forbidden_actions: list[str] = Field(default_factory=list)
    require_nonempty_submission: bool = True
    leak_check: LeakCheck | None = None


class Limits(BaseModel):
    max_call_seconds: float = 180.0
    max_turns: int = 24  # text-path guard


class Scenario(BaseModel):
    """Versioned eval case: who calls, what they know, what answers count."""

    id: str
    problem_id: str
    version: int = 1
    split: Literal["development", "holdout"] = "development"
    language: str = "es"
    description: str = ""
    clock: str | None = None  # ISO datetime anchoring relative dates
    clinic_fixture: str | None = None  # must match dataset meta.name when set
    caller: Caller = Field(default_factory=Caller)
    turns: list[Turn] = Field(default_factory=list)  # voice-path script
    oracle: Oracle
    limits: Limits = Field(default_factory=Limits)
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_keys(cls, data: Any) -> Any:
        """Accept a few old field names so older scenarios keep loading."""
        if isinstance(data, dict):
            if "scenario_id" in data and "id" not in data:
                data["id"] = data.pop("scenario_id")
            if "reference_now" in data and "clock" not in data:
                data["clock"] = data.pop("reference_now")
        return data

    @property
    def scenario_id(self) -> str:
        return self.id

    @property
    def reference_now(self) -> str | None:
        return self.clock

    @property
    def from_number(self) -> str | None:
        return self.caller.from_number

    @property
    def accepted_outcomes(self) -> list[list[dict[str, Any]]]:
        return [list(o.actions) for o in self.oracle.accepted_outcomes]

    @property
    def leak_check(self) -> LeakCheck | None:
        return self.oracle.leak_check

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
    verdict: Literal["pass", "fail", "invalid_evaluation"] = "fail"
    failure_signal: Literal["missing_record", "record_mismatch", "transcript_leak"] | None = None
    categories: list[str] = Field(default_factory=list)  # plan §14 attribution
    matched_outcome: int | None = None
    field_diffs: list[FieldDiff] = Field(default_factory=list)
    extra_actions: list[dict[str, Any]] = Field(default_factory=list)
    missing_actions: list[dict[str, Any]] = Field(default_factory=list)
    submitted: list[dict[str, Any]] = Field(default_factory=list)
    submit_attempts: list[dict[str, Any]] = Field(default_factory=list)
    transcript: list[str] = Field(default_factory=list)
    turn_latencies_ms: list[float] = Field(default_factory=list)
    first_audio_ms: float | None = None
    cost: float | None = None  # None = unknown, never zero (plan §13)
    usage: dict[str, Any] = Field(default_factory=dict)  # provider usage, if exposed
    audio: dict[str, str] = Field(default_factory=dict)  # {"agent": path, "caller": path}
    interrupts: list[dict[str, Any]] = Field(default_factory=list)  # barge-in events
    duration_s: float = 0.0
    errors: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"


class CandidateConfig(BaseModel):
    """How to reach (and optionally start) the agent under test.

    kind=external: an already-running agent reachable at `ws_url`.
    kind=double:   the built-in test double (evaluator self-check).
    """

    name: str
    kind: Literal["external", "double"] = "external"
    ws_url: str | None = None  # e.g. ws://localhost:7860/ws
    text_url: str | None = None  # optional text adapter endpoint
    usage_url: str | None = None  # optional; GET {usage_url}/calls/{call_id} → {cost, usage}
    start_command: str | None = None  # optional; runner waits for ws_url
    env: dict[str, str] = Field(default_factory=dict)
    mode: Literal["correct", "mutate", "silent"] = "correct"  # double only
    port: int | None = None  # double only
    version: str = "unknown"


class SwitchboardConfig(BaseModel):
    """Concurrent-call diagnostic (problem 2): N simultaneous sessions.

    Each parallel call runs a different scenario so cross-talk shows up as
    a wrong verdict for that call. Diagnostic only - worth zero points.
    """

    concurrency: int = 5


class ExperimentConfig(BaseModel):
    name: str
    rules_version: str = "scoring-2.0-draft"
    reference_now: str | None = None  # default anchor for relative dates
    clinic_dataset: str
    clinic_port: int = 8090
    submit_key: str = "pk-local-eval"  # X-Api-Key the local receiver expects
    repetitions: int = 1
    budget: dict[str, Any] = Field(default_factory=dict)  # plan §18 limits
    switchboard: SwitchboardConfig | None = None
    tts_command: str | None = None  # e.g. "espeak-ng"; absent = no voice synth
    candidates: list[CandidateConfig]
    scenarios: list[str]  # paths or globs, relative to the config file

    @classmethod
    def load(cls, path: str) -> ExperimentConfig:
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))
