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
