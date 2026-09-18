"""The three lean questions sent to Jev on every assessed turn.

TypeSafe mixes question types in one request; these three are deliberately
atomic so a wrong answer can be traced to a single, well-scoped judgment. The
question ids are the keys the answers come back under.
"""
from __future__ import annotations

from agent.decision.models import JsonValue, TurnIntent

INTENT_KEY = "intent"
MEDICAL_EMERGENCY_KEY = "medical_emergency"
NEEDS_CLARIFICATION_KEY = "needs_clarification"

QUESTION_KEYS: tuple[str, str, str] = (
    INTENT_KEY,
    MEDICAL_EMERGENCY_KEY,
    NEEDS_CLARIFICATION_KEY,
)

INTENT_INSTRUCTIONS = "Which single scheduling intent best matches the caller's latest turn?"

# The closed choice set. Keys are the TurnIntent values; adding an option here
# without a matching enum member is rejected by the client as malformed.
INTENT_CRITERIA: dict[str, str] = {
    TurnIntent.BOOK_APPOINTMENT.value: "Book a new appointment.",
    TurnIntent.RESCHEDULE_APPOINTMENT.value: "Move an existing appointment to another time.",
    TurnIntent.CANCEL_APPOINTMENT.value: "Cancel an existing appointment.",
    TurnIntent.REGISTER_PATIENT.value: "Register a new patient.",
    TurnIntent.ASK_INFORMATION.value: (
        "Ask about the clinic or an existing appointment without booking, "
        "moving or cancelling."
    ),
    TurnIntent.ESCALATE.value: (
        "Report an emergency or red flag that needs urgent human attention."
    ),
    TurnIntent.OUT_OF_SCOPE.value: (
        "A request outside clinic scheduling, such as medical advice, another "
        "patient's data, or an unrelated topic."
    ),
    TurnIntent.OTHER.value: "None of the above, or the intent is unclear.",
}

MEDICAL_EMERGENCY_INSTRUCTIONS = (
    "Does the caller describe a medical emergency that needs immediate human escalation?"
)
MEDICAL_EMERGENCY_CRITERIA: dict[str, str] = {
    "true": "A medical emergency or red-flag symptom is described.",
    "false": "No medical emergency or red-flag symptom is described.",
}

NEEDS_CLARIFICATION_INSTRUCTIONS = (
    "Does the caller's latest turn need clarification before the agent can act on it?"
)
NEEDS_CLARIFICATION_CRITERIA: dict[str, str] = {
    "true": "The request is ambiguous or missing a detail required to act.",
    "false": "The request is clear enough to act on.",
}


def build_questions() -> dict[str, JsonValue]:
    """Return a fresh questions map for one TypeSafe request."""
    return {
        INTENT_KEY: {
            "type": "choice",
            "instructions": INTENT_INSTRUCTIONS,
            "criteria": dict(INTENT_CRITERIA),
        },
        MEDICAL_EMERGENCY_KEY: {
            "type": "noul",
            "instructions": MEDICAL_EMERGENCY_INSTRUCTIONS,
            "criteria": dict(MEDICAL_EMERGENCY_CRITERIA),
        },
        NEEDS_CLARIFICATION_KEY: {
            "type": "noul",
            "instructions": NEEDS_CLARIFICATION_INSTRUCTIONS,
            "criteria": dict(NEEDS_CLARIFICATION_CRITERIA),
        },
    }


def intent_choice_labels() -> frozenset[str]:
    """The labels a Jev choice answer is allowed to return."""
    return frozenset(INTENT_CRITERIA)


__all__ = [
    "INTENT_CRITERIA",
    "INTENT_INSTRUCTIONS",
    "INTENT_KEY",
    "MEDICAL_EMERGENCY_CRITERIA",
    "MEDICAL_EMERGENCY_INSTRUCTIONS",
    "MEDICAL_EMERGENCY_KEY",
    "NEEDS_CLARIFICATION_CRITERIA",
    "NEEDS_CLARIFICATION_INSTRUCTIONS",
    "NEEDS_CLARIFICATION_KEY",
    "QUESTION_KEYS",
    "build_questions",
    "intent_choice_labels",
]
