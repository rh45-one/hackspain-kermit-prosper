"""Typed input and output for the Jev structured-decision sidecar.

The wire contract follows the official TypeSafe evaluation endpoint
(``POST /v1/systemone``): a ``state``, a pinned ``model`` and a map of typed
``questions``; the response carries one typed answer per question.

Jev output is advisory by construction. ``TurnDecision`` never authorises a
write and this module exposes no method that performs one.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Recursive JSON alias: state is a string, object or array of text values.
type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

# Roles are normalised to the two sides of the call before redaction.
CALLER_ROLE = "caller"
AGENT_ROLE = "agent"
_CALLER_ROLES = frozenset({"caller", "user", "patient", "client", "customer"})

# Label applied wherever a protected value was stripped.
REDACTED = "[REDACTED]"

# The sidecar identity reported on every decision.
SOURCE = "typesafe.jev"

# The versioned TypeSafe model pinned by the OpenSpec (alias `jev-latest`).
DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_TIMEOUT_SECONDS = 0.300
DEFAULT_MIN_CONFIDENCE = 0.5
DEFAULT_NOUL_THRESHOLD = 0.5


class TurnIntent(StrEnum):
    """Closed scheduling-intent vocabulary Jev picks from."""

    BOOK_APPOINTMENT = "book_appointment"
    RESCHEDULE_APPOINTMENT = "reschedule_appointment"
    CANCEL_APPOINTMENT = "cancel_appointment"
    REGISTER_PATIENT = "register_patient"
    ASK_INFORMATION = "ask_information"
    ESCALATE = "escalate"
    OUT_OF_SCOPE = "out_of_scope"
    OTHER = "other"


class AbstentionReason(StrEnum):
    """Why ``assess_current_turn`` returned no usable decision."""

    MISSING_KEY = "missing_key"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    TRANSPORT_ERROR = "transport_error"
    MALFORMED_RESPONSE = "malformed_response"
    LOW_CONFIDENCE = "low_confidence"
    EMPTY_STATE = "empty_state"
    INVALID_INPUT = "invalid_input"


def normalize_role(role: str) -> str:
    """Collapse provider roles to ``caller`` or ``agent``."""
    return CALLER_ROLE if str(role).strip().lower() in _CALLER_ROLES else AGENT_ROLE


@dataclass(frozen=True, slots=True)
class TranscriptTurn:
    """One finalized turn of the server-owned transcript."""

    role: str
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", normalize_role(self.role))
        object.__setattr__(self, "text", str(self.text))

    def as_wire(self) -> dict[str, str]:
        return {"role": self.role, "text": self.text}


@dataclass(frozen=True, slots=True)
class TurnDecisionInput:
    """Server-owned snapshot of the current turn.

    Built exclusively from the per-socket ``CallContext`` (finalized caller
    transcript plus call state). It is never populated from model-supplied
    tool arguments; the sidecar's public API accepts only this object.
    """

    transcript: tuple[TranscriptTurn, ...] = ()
    context: Mapping[str, JsonValue] = field(default_factory=dict)
    language: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "transcript", tuple(self.transcript))
        object.__setattr__(self, "context", dict(self.context))

    @classmethod
    def from_messages(
        cls,
        messages: Sequence[Mapping[str, Any] | TranscriptTurn],
        context: Mapping[str, JsonValue] | None = None,
        language: str | None = None,
    ) -> TurnDecisionInput:
        """Normalise a role/text message list from server state."""
        turns: list[TranscriptTurn] = []
        for message in messages:
            if isinstance(message, TranscriptTurn):
                turns.append(message)
            else:
                turns.append(
                    TranscriptTurn(
                        role=str(message.get("role", AGENT_ROLE)),
                        text=str(message.get("text", "")),
                    )
                )
        return cls(transcript=tuple(turns), context=dict(context or {}), language=language)

    def is_empty(self) -> bool:
        return not self.transcript and not self.context


@dataclass(frozen=True, slots=True)
class TurnDecision:
    """Advisory, typed assessment returned to the audio host.

    ``intent``/``medical_emergency``/``needs_clarification`` are ``None``
    whenever ``abstained`` is true, so the host can proceed exactly as if Jev
    were absent. ``source``, ``model``, ``latency_ms``, ``confidence`` and the
    abstention metadata make every call observable without logging content.
    """

    intent: TurnIntent | None = None
    medical_emergency: bool | None = None
    needs_clarification: bool | None = None
    confidence: float | None = None
    abstained: bool = True
    abstention_reason: AbstentionReason | None = AbstentionReason.EMPTY_STATE
    source: str = SOURCE
    model: str | None = None
    latency_ms: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def advisory(self) -> bool:
        """Jev output can annotate a decision; it can never authorise one."""
        return True

    def as_audit_dict(self) -> dict[str, Any]:
        """PII-free projection safe for logs, traces and the call audit."""
        return {
            "advisory": True,
            "abstained": self.abstained,
            "abstention_reason": None if self.abstention_reason is None else str(self.abstention_reason),
            "intent": None if self.intent is None else str(self.intent),
            "medical_emergency": self.medical_emergency,
            "needs_clarification": self.needs_clarification,
            "confidence": self.confidence,
            "source": self.source,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


# --------------------------------------------------------------------------
# Wire response schema (untrusted remote output, validated strictly).
# --------------------------------------------------------------------------


class _WireModel(BaseModel):
    # Unknown extra fields are ignored so a benign additive release cannot
    # force an abstention; missing or mistyped required fields still fail.
    model_config = ConfigDict(extra="ignore")


class NoulAnswer(_WireModel):
    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0)


class ChoiceAnswer(_WireModel):
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)


class ScoreAnswer(_WireModel):
    type: Literal["score"]
    score: float
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)


type Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]


class Usage(_WireModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class SystemOneResponse(_WireModel):
    model: str
    answers: dict[str, Answer]
    usage: Usage
