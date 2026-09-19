"""Offline tests for the pipeline's phone-hint greeting and wiring.

The developer context may carry at most the patient's given name from the
caller-id hint: caller id is a hint, never identification, so the greeting
must never leak a surname, date of birth, national id or phone number.
"""
from __future__ import annotations

from typing import Any

from agent.voice.pipeline import phone_hint_greeting
from tests.conftest import load_fixture


class HintCtx:
    """Minimal ctx carrying just what phone_hint_greeting reads."""

    def __init__(self, phone_hint_match: dict[str, Any] | None = None) -> None:
        self.phone_hint_match = phone_hint_match


def hinted_ctx() -> HintCtx:
    """A hint built the way ToolBox.prepare_phone_hint stores it: safe fields only."""
    match = load_fixture("directory")["matches"][0]
    safe = {
        k: v
        for k, v in match.items()
        if k
        in (
            "patient_id",
            "given_name",
            "first_surname",
            "second_surname",
            "date_of_birth",
            "sex",
            "has_visited_before",
            "insurer",
            "referrals",
            "note",
            "matched_fields",
        )
    }
    return HintCtx(safe)


def test_hint_greeting_uses_only_the_given_name():
    message = phone_hint_greeting(hinted_ctx())

    assert "Marta" in message
    # At most the given name: nothing else from the record may appear.
    assert "Ruiz" not in message
    assert "Gómez" not in message
    assert "1988-03-14" not in message
    assert "12345678Z" not in message
    assert "612345678" not in message
    # The hint is framed as a hint: identity still needs the lookup flow.
    assert "lookup_patient" in message
    assert "confirm_patient" in message
    # Third-party callers stay possible: the person on the line may not be
    # whoever the line belongs to, and the hint is dropped when it does not fit.
    assert "may not be" in message
    assert "drop the hint" in message
    # One confirming detail, not two. A full Spanish name over a telephone is
    # slow and easily misheard, and the record is already open from the
    # caller id — asking for it again spends a turn of a three-minute call.
    assert "date of birth" in message
    assert "a full name over a telephone is slow" in message
    # The opening greets and listens; it does not interrogate before it knows
    # what the caller wants, and the caller may be ringing about someone else.
    assert "let them say what they want first" in message
    assert "calling about somebody else" in message


def test_without_hint_the_greeting_is_generic():
    message = phone_hint_greeting(HintCtx(None))

    assert "Marta" not in message
    assert "hint" in message  # generic text still mentions chart hints safely


def test_withheld_number_shape_greets_generically():
    """A hint dict without a usable given name degrades to the generic text."""
    message = phone_hint_greeting(HintCtx({"patient_id": "P00042"}))

    assert "Marta" not in message
    assert "lookup_patient" not in message


def test_greeting_never_contains_the_caller_number():
    class NumberedCtx(HintCtx):
        from_number = "+34612345678"

    message = phone_hint_greeting(NumberedCtx(hinted_ctx().phone_hint_match))

    assert "612345678" not in message
    assert "+34612345678" not in message


def test_noise_suppression_is_off_unless_asked_for():
    """Ten concurrent calls cannot afford it, so it never turns itself on.

    RNNoise measures 2.48 ms per 20 ms frame on this path. One call absorbs
    that; ten on one event loop would ask for 1240 ms of CPU per second of
    audio, and a loop that falls behind is the failure this whole path
    exists to avoid. It is a deployment decision, never a default.
    """
    from agent.voice.pipeline import _noise_filter

    class _Off:
        pass

    class _On:
        noise_suppression = True

    assert _noise_filter(_Off()) is None
    assert _noise_filter(_On()) is not None  # available when explicitly asked for


def test_the_greeting_is_bilingual():
    """A Spanish-only greeting anchors the model into Spanish for the call.

    Observed live on call 98bd199c: the agent opened "Buenos días, le atiende
    Clínica Arenal", the caller said "Hello. Are you still there?", and the
    agent answered in Spanish twice more while the caller asked in English
    whether anyone could hear them. The call died at 76 s with no action.
    """
    for message in (phone_hint_greeting(hinted_ctx()), phone_hint_greeting(HintCtx(None))):
        assert "BILINGUAL" in message
        assert "buenos días" in message
        assert "Good morning" in message
