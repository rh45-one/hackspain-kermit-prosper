"""Offline tests pinning the exact three-question TypeSafe payload schema."""
from __future__ import annotations

from agent.decision import (
    INTENT_CRITERIA,
    INTENT_KEY,
    MEDICAL_EMERGENCY_KEY,
    NEEDS_CLARIFICATION_KEY,
    QUESTION_KEYS,
    TurnIntent,
    build_questions,
)
from agent.decision.questions import (
    MEDICAL_EMERGENCY_CRITERIA,
    NEEDS_CLARIFICATION_CRITERIA,
    intent_choice_labels,
)


def test_exactly_three_leaned_questions():
    questions = build_questions()
    assert tuple(questions) == QUESTION_KEYS
    assert set(questions) == {INTENT_KEY, MEDICAL_EMERGENCY_KEY, NEEDS_CLARIFICATION_KEY}


def test_intent_is_a_choice_over_the_closed_vocabulary():
    intent = build_questions()[INTENT_KEY]
    assert intent["type"] == "choice"
    assert intent["criteria"] == INTENT_CRITERIA
    assert set(intent["criteria"]) == {intent.value for intent in TurnIntent}
    assert len(intent["criteria"]) == 8


def test_emergency_and_clarification_are_nouls_with_criteria():
    questions = build_questions()
    emergency = questions[MEDICAL_EMERGENCY_KEY]
    clarification = questions[NEEDS_CLARIFICATION_KEY]
    assert emergency["type"] == "noul"
    assert emergency["criteria"] == MEDICAL_EMERGENCY_CRITERIA
    assert set(emergency["criteria"]) == {"true", "false"}
    assert clarification["type"] == "noul"
    assert clarification["criteria"] == NEEDS_CLARIFICATION_CRITERIA


def test_instructions_are_non_empty_strings():
    for question in build_questions().values():
        assert isinstance(question["instructions"], str)
        assert question["instructions"].strip()


def test_build_questions_returns_a_fresh_mutable_map():
    first = build_questions()
    first[INTENT_KEY]["criteria"]["book_appointment"] = "mutated"
    second = build_questions()
    assert second[INTENT_KEY]["criteria"]["book_appointment"] == INTENT_CRITERIA["book_appointment"]


def test_intent_choice_labels_match_criteria_keys():
    assert intent_choice_labels() == frozenset(INTENT_CRITERIA)
