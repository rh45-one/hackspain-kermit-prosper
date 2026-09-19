"""The other direction: the clinic ringing a colleague, not answering a patient.

A receptionist prompt used for this would ask a doctor for their date of birth.
"""
from __future__ import annotations

from agent.brain import prompts
from agent.brain.tools import ToolBox
from agent.voice.context import CallContext
from agent.voice.pipeline import system_prompt_for


def _ctx(tmp_path, brief=None) -> CallContext:
    ctx = CallContext(data_dir=str(tmp_path / "d"), call_id="cover-1")
    ctx.cover_brief = brief
    return ctx


def test_without_a_brief_it_is_still_the_receptionist(tmp_path):
    assert system_prompt_for(_ctx(tmp_path)) == prompts.SYSTEM_PROMPT


def test_a_brief_turns_it_into_the_clinic_calling_out(tmp_path):
    prompt = system_prompt_for(
        _ctx(tmp_path, {"who": "Coordinación", "because": "El Dr. Requena está de baja",
                        "urgency": "today", "gap": "lunes por la mañana"})
    )

    assert prompts.COVER_PROMPT[:60] in prompt
    # The facts travel in, so it opens knowing what broke instead of asking.
    assert "El Dr. Requena está de baja" in prompt
    assert "lunes por la mañana" in prompt
    # And it must not be the receptionist at the same time.
    assert prompts.SYSTEM_PROMPT not in prompt


def test_the_cover_call_cannot_reach_a_patient_tool(tmp_path):
    """Every extra tool is one more thing it can reach for by mistake."""

    from tests.test_brain_tools import FakeSettings

    box = ToolBox(_ctx(tmp_path, {"who": "Coordinación"}), FakeSettings())
    names = {getattr(t, "__name__", getattr(getattr(t, "func", None), "__name__", str(t))) for t in box.tools()}

    assert "record_cover_answer" in names
    for patient_tool in ("book_appointment", "register_new_patient", "lookup_patient"):
        assert patient_tool not in names


def test_the_brief_says_which_language_to_open_in(tmp_path):
    """We know who is picking up, so guessing would be ignoring what we know."""
    prompt = system_prompt_for(
        _ctx(tmp_path, {"who": "Dra. Carmen Ortiz Vidal", "speaks": "català, inglés, español"})
    )

    assert "català, inglés, español" in prompt
    assert "Abre en ese idioma" in prompt


def test_a_colleague_we_cannot_place_leaves_the_language_unsaid(tmp_path):
    """Better unsaid than invented: the model then does what it does inbound."""
    from agent.voice.server import _languages_of

    assert _languages_of("") == ""
    assert _languages_of("PR-does-not-exist") == ""


def test_the_per_person_profile_reaches_the_prompt(tmp_path):
    """Somebody who knows this colleague writes how to open with them."""
    prompt = system_prompt_for(
        _ctx(tmp_path, {
            "who": "Dra. Carmen Ortiz Vidal",
            "opening": "Tutéala, lleva quince años aquí",
            "may_ask": "si puede doblar el sábado",
            "must_not_ask": "nada de guardias de noche, tiene una excedencia",
        })
    )

    assert "Tutéala, lleva quince años aquí" in prompt
    assert "si puede doblar el sábado" in prompt
    assert "nada de guardias de noche" in prompt


def test_a_clinic_that_configured_nothing_behaves_as_it_always_did(tmp_path):
    """Defaults answer, so the directory arriving changes nobody's calls."""
    from agent.clinic import graph

    route = graph.who_to_call("provider_on_leave")

    assert route is not None
    assert route.target == "manager"
    assert route.urgency == "today"
