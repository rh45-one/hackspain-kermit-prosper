"""The three lean questions sent to Jev on every assessed turn.

TypeSafe mixes question types in one request; these three are deliberately
atomic so a wrong answer can be traced to a single, well-scoped judgment. The
question ids are the keys the answers come back under.
"""
from __future__ import annotations

from collections.abc import Mapping

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


PLAN_KEY = "plan"
PLAN_UNCLEAR = "unclear"
PLAN_INSTRUCTIONS = (
    "The caller was asked which insurance plan they hold and this is what the "
    "line delivered, often badly. Which of the clinic's plans did they say? "
    "Answer 'unclear' unless the words really do point at one of them — a plan "
    "nobody said is worse than asking again."
)


def build_plan_question(plans: Mapping[str, str]) -> dict[str, JsonValue]:
    """A closed choice over the plans the clinic actually sells.

    ``plans`` maps plan id to the name a caller would say, and comes from the
    live catalogue, so a plan signed tomorrow is an option tomorrow without
    anyone editing this file. The escape hatch is always offered: this exists
    because a model invented a plan rather than admit it had not heard one.
    """
    criteria: dict[str, str] = {
        plan_id: f"The caller said {name!r}." for plan_id, name in plans.items()
    }
    criteria[PLAN_UNCLEAR] = (
        "The words do not point at any one of these plans, or point at more "
        "than one. The agent must ask the caller again."
    )
    return {
        PLAN_KEY: {
            "type": "choice",
            "instructions": PLAN_INSTRUCTIONS,
            "criteria": criteria,
        }
    }


COVER_KEY = "cover"
COVER_UNCLEAR = "unclear"
COVER_INSTRUCTIONS = (
    "A shift at the clinic has been left uncovered and somebody has to be "
    "rung about it. Given what happened and who is on the rota, which single "
    "person should be called? Answer 'unclear' unless one of them is clearly "
    "the right call — ringing the wrong colleague costs more than asking a "
    "human which one."
)


def build_cover_question(people: Mapping[str, str]) -> dict[str, JsonValue]:
    """A closed choice over the people this clinic can actually ring.

    ``people`` maps slug to a line describing them — role, what they cover,
    what they may be asked. It comes from the organisation's own directory, so
    a colleague hired today is an option today and nobody edits this file.

    The escape hatch is always offered and it is the point. A rota where
    nobody hesitates is a rota that one day wakes the cardiologist about a
    sprained ankle.
    """
    criteria: dict[str, str] = dict(people)
    criteria[COVER_UNCLEAR] = (
        "No single one of them is clearly right, or the situation needs a "
        "person to decide. Fall back to whoever the clinic configured."
    )
    return {
        COVER_KEY: {
            "type": "choice",
            "instructions": COVER_INSTRUCTIONS,
            "criteria": criteria,
        }
    }


TRIAGE_KEY = "likely_specialty"
TRIAGE_UNCLEAR = "unclear"
TRIAGE_INSTRUCTIONS = (
    "From this patient's record, which of the clinic's specialties is the most "
    "likely reason they will call next? Judge only from what the record says — "
    "past visits, referrals on file, their plan, their age. Choose 'unclear' "
    "whenever the record does not point anywhere in particular, which is the "
    "normal case for a healthy adult who has never been seen."
)


def build_triage_question(specialties: Mapping[str, str]) -> dict[str, JsonValue]:
    """A closed choice over the specialties THIS clinic actually offers.

    The escape hatch matters more here than anywhere else. A record with
    nothing in it points nowhere, and a panel that answers "cardiology" for
    everybody who has never been seen is worse than a blank column: it looks
    like knowledge and it is noise.
    """
    criteria: dict[str, str] = dict(specialties)
    criteria[TRIAGE_UNCLEAR] = (
        "The record does not point at any specialty in particular. Healthy, "
        "no referrals, nothing recurring."
    )
    return {
        TRIAGE_KEY: {
            "type": "choice",
            "instructions": TRIAGE_INSTRUCTIONS,
            "criteria": criteria,
        }
    }


def intent_choice_labels() -> frozenset[str]:
    """The labels a Jev choice answer is allowed to return."""
    return frozenset(INTENT_CRITERIA)


__all__ = [
    "COVER_KEY",
    "COVER_UNCLEAR",
    "INTENT_CRITERIA",
    "INTENT_INSTRUCTIONS",
    "INTENT_KEY",
    "MEDICAL_EMERGENCY_CRITERIA",
    "MEDICAL_EMERGENCY_INSTRUCTIONS",
    "MEDICAL_EMERGENCY_KEY",
    "NEEDS_CLARIFICATION_CRITERIA",
    "NEEDS_CLARIFICATION_INSTRUCTIONS",
    "NEEDS_CLARIFICATION_KEY",
    "PLAN_INSTRUCTIONS",
    "PLAN_KEY",
    "PLAN_UNCLEAR",
    "QUESTION_KEYS",
    "TRIAGE_KEY",
    "TRIAGE_UNCLEAR",
    "build_cover_question",
    "build_plan_question",
    "build_questions",
    "build_triage_question",
    "intent_choice_labels",
]
