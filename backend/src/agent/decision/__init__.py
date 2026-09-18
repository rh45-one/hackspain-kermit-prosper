"""Isolated TypeSafe Jev structured-decision sidecar (advisory only).

Jev assesses the latest finalized caller turn and returns a typed
:class:`~agent.decision.models.TurnDecision` or an explicit abstention. It
never writes, never authorises, never handles turn-taking and never calls the
clinic API; the deterministic tools remain the only source of a scheduling
action.
"""
from __future__ import annotations

from agent.decision.client import ENDPOINT_PATH, JevClient
from agent.decision.models import (
    AGENT_ROLE,
    CALLER_ROLE,
    DEFAULT_BASE_URL,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MODEL,
    DEFAULT_NOUL_THRESHOLD,
    DEFAULT_TIMEOUT_SECONDS,
    REDACTED,
    SOURCE,
    AbstentionReason,
    TranscriptTurn,
    TurnDecision,
    TurnDecisionInput,
    TurnIntent,
)
from agent.decision.questions import (
    INTENT_CRITERIA,
    INTENT_KEY,
    MEDICAL_EMERGENCY_KEY,
    NEEDS_CLARIFICATION_KEY,
    QUESTION_KEYS,
    build_questions,
)
from agent.decision.redaction import (
    ALLOWED_KEYS,
    is_sensitive_key,
    redact_text,
    redact_turn_input,
    redact_value,
)

__all__ = [
    "AGENT_ROLE",
    "ALLOWED_KEYS",
    "CALLER_ROLE",
    "DEFAULT_BASE_URL",
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_MODEL",
    "DEFAULT_NOUL_THRESHOLD",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENDPOINT_PATH",
    "INTENT_CRITERIA",
    "INTENT_KEY",
    "MEDICAL_EMERGENCY_KEY",
    "NEEDS_CLARIFICATION_KEY",
    "QUESTION_KEYS",
    "REDACTED",
    "SOURCE",
    "AbstentionReason",
    "JevClient",
    "TranscriptTurn",
    "TurnDecision",
    "TurnDecisionInput",
    "TurnIntent",
    "build_questions",
    "is_sensitive_key",
    "redact_text",
    "redact_turn_input",
    "redact_value",
]
