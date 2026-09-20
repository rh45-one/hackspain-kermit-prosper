"""Core data models: actions, scenarios, case results, run manifest.

Canonical action form is flat: `{"action": "BOOK", "patient_id": ..., ...}`.
`REGISTER` payloads may arrive nested under `new_patient` (the record
readback shape) or flat (the submit body shape); both canonicalize flat.

Scenario schema follows the evaluator plan §8: `caller` (persona, facts,
behavior), `oracle` (accepted outcomes + extra checks) and `limits`.

The call/evidence schema (`CaseResult`, `TranscriptEvent`, `EvidenceAvailability`)
carries an explicit `schema_version`. Nothing in this file may require a manual
migration to read an older artifact: the reader infers the missing pieces and
never turns "nobody measured it" into a zero.
"""
from __future__ import annotations

import json
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# Version of the call/evidence artifact schema (`cases.jsonl`) and of the
# transcript/evidence sub-schemas. Bump it when a written field changes shape;
# a reader must keep loading older numbers, so this is informative, never a gate.
SCHEMA_VERSION = 2
# Artifacts written before the field existed. Version 1 is `CaseResult` on
# pydantic defaults: no origin, no evidence availability, no transcript events.
LEGACY_SCHEMA_VERSION = 1

# Who produced a call. `real` is a call the backend actually served (read back
# from its audit), `simulated` is a scripted experiment case, `manual` is a
# person on the console, `unknown` is a legacy artifact that never said.
CallOrigin = Literal["real", "simulated", "manual", "unknown"]

# Evidence availability is a three-state fact per item, never a boolean and
# never a zero: `unknown` means nobody measured it, `absent` means the source
# says it does not exist (a real call with no recording), `present` means it is
# in this artifact. `False`/`0` would be a claim we cannot support.
EvidenceState = Literal["present", "absent", "unknown"]

TranscriptRole = Literal["caller", "agent", "system", "unknown"]

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


class TranscriptEvent(BaseModel):
    """One ordered transcript record, exactly as the source recorded it.

    A backend audit, a text adapter and a person typing all produce ordered
    fragments, not tidy turns. `fragment=True` says the source gave a piece and
    the evaluator refused to invent a turn boundary around it: turn detection
    is the agent's job and a guessed boundary would be a fabricated fact.
    `timestamp` is whatever the source stamped (ISO-8601 for the backend audit);
    `offset_s` is seconds from the start of the call when that is derivable.
    """

    role: TranscriptRole = "unknown"
    text: str = ""
    timestamp: str | None = None
    offset_s: float | None = None
    fragment: bool = False
    source: str | None = None  # agent_audit | text_adapter | manual | legacy_transcript


class EvidenceAvailability(BaseModel):
    """Which evidence this call actually carries, item by item.

    Every item is `present` / `absent` / `unknown`; a missing recording is
    `absent` (the source has none) or `unknown` (nobody looked), and never a
    silent zero. Consumers show the coverage instead of assuming it.
    """

    audio: EvidenceState = "unknown"
    transcript: EvidenceState = "unknown"
    cost: EvidenceState = "unknown"
    outcome: EvidenceState = "unknown"

    def as_dict(self) -> dict[str, EvidenceState]:
        return {
            "audio": self.audio,
            "transcript": self.transcript,
            "cost": self.cost,
            "outcome": self.outcome,
        }


# Tokens picked from the observer run builder (`observer/run.py`, frozen for P0):
# a real call always lands under `.../obs-<id>` and always says so in its notes.
# They are only consulted when a legacy artifact carries no `origin` at all.
_LEGACY_REAL_MARKERS = ("/obs-", "llamada real observada del audit")
_LEGACY_ROLE_PREFIXES: dict[str, TranscriptRole] = {
    "caller": "caller",
    "agente": "agent",
    "agent": "agent",
    "assistant": "agent",
    "system": "system",
}


def _legacy_origin(data: dict[str, Any]) -> CallOrigin:
    """Guess the origin of an artifact written before `origin` existed.

    Only two outcomes are possible and both are conservative: a call whose
    identifiers match the observer's real-call shape is `real`, everything else
    is `simulated` (the scripted runner). Nothing is invented as `manual`.
    """
    notes = data.get("notes")
    if isinstance(notes, str):
        notes = [notes]
    note_text = " ".join(str(n) for n in notes) if isinstance(notes, list) else ""
    haystack = f"{data.get('case_id') or ''} {note_text}"
    return "real" if any(marker in haystack for marker in _LEGACY_REAL_MARKERS) else "simulated"


def _legacy_transcript_events(lines: Any) -> list[dict[str, Any]]:
    """Turn old `transcript` display lines into ordered, unflagged-turn events.

    The legacy field is a list of `"<who>: <what>"` strings, one per recorded
    fragment. Each line becomes one event with `fragment=True` and no timestamp:
    the reader recovers the order the artifact had, and claims nothing more.
    """
    if not isinstance(lines, list):
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, str) or not line.strip():
            continue
        label, separator, rest = line.partition(": ")
        role: TranscriptRole = "unknown"
        text = line.strip()
        if separator and label.strip().lower() in _LEGACY_ROLE_PREFIXES:
            role = _LEGACY_ROLE_PREFIXES[label.strip().lower()]
            text = rest.strip()
        events.append(
            {
                "role": role,
                "text": text,
                "fragment": True,
                "source": "legacy_transcript",
            }
        )
    return events


def _legacy_evidence(data: dict[str, Any]) -> dict[str, EvidenceState]:
    """Availability of a legacy artifact, read from what it does carry.

    `absent` is only claimed where the artifact itself says the evidence does
    not exist; where it is merely missing, the answer is `unknown`.
    """
    audio = data.get("audio")
    transcript = data.get("transcript")
    events = data.get("transcript_events")
    verdict = data.get("verdict")
    return {
        "audio": "present" if audio else "unknown",
        "transcript": "present" if (transcript or events) else "unknown",
        "cost": "present" if data.get("cost") is not None else "unknown",
        "outcome": "absent" if verdict == "invalid_evaluation" else "present",
    }


class CaseResult(BaseModel):
    """One evaluated call, with an explicit version, origin and evidence map.

    Reading is tolerant by design: an artifact written by an earlier run loads
    with no manual migration (missing `schema_version`, `origin`, `evidence` and
    `transcript_events` are inferred), and unknown extra fields are ignored.
    """

    # The version of the object in hand: a freshly written case declares the
    # current version, while `model_validate_json` records what a file says.
    schema_version: int = SCHEMA_VERSION
    # `real` / `simulated` / `manual`; a legacy artifact that never said falls
    # back to the inference in `_legacy_origin`, never to a fabricated value.
    origin: CallOrigin = "simulated"
    candidate_version: str | None = None
    run_id: str | None = None  # link back to the run that produced this case
    started_at: str | None = None
    ended_at: str | None = None
    evidence: EvidenceAvailability = Field(default_factory=EvidenceAvailability)
    # Ordered fragments with role and timestamp. `transcript` (below) stays for
    # the per-speaker rendering old consumers read; it is not a turn model.
    transcript_events: list[TranscriptEvent] = Field(default_factory=list)
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
    # Wire counters and audio volume, when the harness measured them. None on
    # paths that never opened a socket (text adapter) and on old runs, so the
    # console reads `n/d` instead of a zero nobody measured.
    frames_sent: int | None = None
    frames_received: int | None = None
    caller_audio_s: float | None = None
    agent_audio_s: float | None = None
    interrupts: list[dict[str, Any]] = Field(default_factory=list)  # barge-in events
    # Oracle checks the rig could not evaluate on this path (e.g. leak_check
    # needs a transcript, and the voice path has no STT). Never silently
    # counted as passed.
    checks_not_run: list[str] = Field(default_factory=list)
    # Diagnostics that never touch the verdict: things worth seeing but which
    # are nobody's failure, like an agent that does not implement the optional
    # hangup. Best effort has to stay best effort AND stay visible - a signal
    # swallowed in silence is how this project loses runs.
    notes: list[str] = Field(default_factory=list)
    duration_s: float = 0.0
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _tolerant_reader(cls, data: Any) -> Any:
        """Read artifacts from earlier runs without a migration step.

        Only the *shape* is repaired here: a case that never declared an origin,
        an evidence map or ordered transcript events gets them inferred from what
        it does carry, and the inferences are marked as such (`fragment=True`,
        `source="legacy_transcript"`). The version is handled by
        `model_validate_json` below, which is the door every artifact on disk
        comes through.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not data.get("origin"):
            data["origin"] = _legacy_origin(data)
        if not data.get("transcript_events"):
            data["transcript_events"] = _legacy_transcript_events(data.get("transcript"))
        if not data.get("evidence"):
            data["evidence"] = _legacy_evidence(data)
        return data

    @classmethod
    def model_validate_json(cls, json_data: Any, **kwargs: Any) -> CaseResult:
        """Read one JSONL line, recording the version the artifact declares.

        This is where "no manual migration" happens: a line written before the
        field existed is read as `LEGACY_SCHEMA_VERSION` rather than relabelled
        as the current version, so a consumer can tell an upgraded artifact from
        one that always declared its evidence map. An object built in Python (any
        writer calling `CaseResult(...)`) declares the current version instead.
        """
        if isinstance(json_data, (str, bytes, bytearray)):
            try:
                parsed = json.loads(json_data)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                if "schema_version" not in parsed:
                    parsed["schema_version"] = LEGACY_SCHEMA_VERSION
                return cls.model_validate(parsed, **kwargs)
        return super().model_validate_json(json_data, **kwargs)

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    @property
    def ordered_transcript(self) -> list[TranscriptEvent]:
        """The transcript as recorded order, never re-grouped into turns."""
        return list(self.transcript_events)


class CandidateConfig(BaseModel):
    """How to reach (and optionally start) the agent under test.

    kind=external: an already-running agent reachable at `ws_url`.
    kind=double:   the built-in test double (evaluator self-check).

    `text_url` takes precedence over `ws_url` for both kinds: it selects
    the text adapter path (see README, "Adaptador de texto `/turns`").
    """

    name: str
    kind: Literal["external", "double"] = "external"
    ws_url: str | None = None  # e.g. ws://localhost:7860/ws
    text_url: str | None = None  # optional text adapter endpoint
    # One `/turns` POST covers a whole agent turn: several LLM round-trips
    # plus its tool calls against the clinic. Measured p95 ≈ 14 s, max 20 s
    # on a real agent, so the cap is a runaway guard, not a latency budget.
    text_timeout_seconds: float = 120.0
    usage_url: str | None = None  # optional; GET {usage_url}/calls/{call_id} → {cost, usage}
    start_command: str | None = None  # optional; the runner waits for ws_url
    start_cwd: str | None = None
    engine: str | None = None
    runtime_identity: dict[str, Any] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    mode: Literal["correct", "mutate", "silent"] = "correct"  # double only
    port: int | None = None  # double only
    version: str = "unknown"
    # Declarative environment matrix: one entry per variant, `suffix -> env
    # overrides`. The runner expands each variant into its own candidate named
    # `<name>-<suffix>`, so an A/B of two environment settings is a config
    # change, not a hand-written duplicate of the whole candidate block.
    variants: dict[str, dict[str, str]] = Field(default_factory=dict)


def expand_candidates(candidates: list[CandidateConfig]) -> list[CandidateConfig]:
    """Expand `variants` into one candidate per environment variant.

    A candidate without variants passes through untouched. The variant name is
    `<name>-<suffix>` and its env is the base env overridden by the variant's
    keys - so an experiment can declare one agent and a matrix of settings
    instead of hand-copying near-identical blocks. Duplicate resulting names
    are an error: two candidates that cannot be told apart in a report are
    worse than a config that refuses to load.
    """
    out: list[CandidateConfig] = []
    for candidate in candidates:
        if not candidate.variants:
            out.append(candidate)
            continue
        for suffix, overrides in candidate.variants.items():
            out.append(
                candidate.model_copy(
                    update={
                        "name": f"{candidate.name}-{suffix}",
                        "env": {**candidate.env, **overrides},
                        "variants": {},
                    }
                )
            )
    names = [candidate.name for candidate in out]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"candidatos duplicados tras expandir variantes: {duplicates}")
    return out


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
    clinic_port: int = 18090
    clinic_mode: Literal["managed", "existing"] = "managed"
    clinic_url: str | None = None
    submit_key: str = "pk-local-eval"  # X-Api-Key the local receiver expects
    repetitions: int = 1
    budget: dict[str, Any] = Field(default_factory=dict)  # plan §18 limits
    switchboard: SwitchboardConfig | None = None
    tts_command: str | None = None  # e.g. "espeak-ng"; absent = no voice synth
    # After the call closes, how long to keep polling the receiver before
    # reading the record. The submission window stays open 30 s after the
    # socket closes, so an agent that flushes on hangup needs the grace.
    submit_drain_s: float = 2.0
    candidates: list[CandidateConfig]
    scenarios: list[str]  # paths or globs, relative to the config file

    @model_validator(mode="after")
    def _expand_variants(self) -> ExperimentConfig:
        """Every consumer sees the expanded matrix, never the template."""
        self.candidates = expand_candidates(self.candidates)
        return self

    @classmethod
    def load(cls, path: str) -> ExperimentConfig:
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))
