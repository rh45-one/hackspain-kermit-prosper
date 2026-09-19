"""The other direction: the clinic ringing a colleague, not answering a patient.

A receptionist prompt used for this would ask a doctor for their date of birth.
"""
from __future__ import annotations

from agent.brain import prompts
from agent.orgs import DEFAULT_ORG_ID
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


def _cache_with_week():
    """A catalogue that publishes a week, the way the real one does."""
    day = lambda w, i: type("D", (), {"weekday": w, "intervals": i})()
    sched = type("S", (), {"location_name": "Arenal Norte",
                           "days": [day("monday", ["09:00–14:00"]), day("tuesday", ["09:00–14:00"])]})()
    provider = type("P", (), {"schedules": [sched]})()
    return type("C", (), {"warmed": True, "provider_by_id": staticmethod(lambda _id: provider)})()


def test_the_gap_is_read_off_the_published_week():
    """"Nos hemos quedado sin ginecología" leaves them asking when and where."""
    from agent.clinic import rota

    assert rota.gap_sentence(_cache_with_week(), "PR02", "monday") == (
        "lunes de 09:00 a 14:00 en Arenal Norte"
    )


def test_a_colleague_already_in_clinic_that_day_is_flagged():
    """Asking somebody to cover a morning they already work is how people stop picking up."""
    from agent.clinic import rota

    assert rota.already_working(_cache_with_week(), "PR02", "monday")
    assert rota.already_working(_cache_with_week(), "PR02", "sunday") == ""


def test_a_week_the_catalogue_cannot_say_is_left_out_rather_than_invented():
    from agent.clinic import rota

    assert rota.gap_sentence(None, "PR02", "monday") == ""
    assert rota.gap_sentence(_cache_with_week(), "", "monday") == ""


# ---- the brief carries WHO you are ringing, not just their name -----------
def test_the_brief_says_what_this_person_does_and_who_is_missing(accounts_db):
    """Three people, three different calls — or it is the same call thrice.

    Without a role and a detail the prompt treated a coordinator, a podiatrist
    and the doctor on call as the same person under different names, and it
    sounded like it. And without "who is missing" the opening could not say
    what had happened, which is the first thing anybody picking up asks.
    """
    from agent.accounts.directory import cover_brief
    from agent.accounts.store import Person, Route, Store

    shop = Store(accounts_db)
    shop.upsert_person(DEFAULT_ORG_ID, Person(slug="ana", name="Ana Ruiz", role="Ginecóloga"))
    shop.upsert_person(
        DEFAULT_ORG_ID,
        Person(
            slug="bea",
            name="Bea Lis",
            role="Ginecóloga Jr.",
            detail="Segunda de Ana.",
            covers_for="ana",
        ),
    )
    shop.upsert_route(
        DEFAULT_ORG_ID, Route(reason="provider_on_leave", person_slug="bea", urgency="today")
    )

    brief = cover_brief(DEFAULT_ORG_ID, "provider_on_leave")

    assert brief["who"] == "Bea Lis"
    assert brief["role"] == "Ginecóloga Jr."
    assert brief["about_them"] == "Segunda de Ana."
    # Whom she stands in for is whom the call is about, and nobody had to say so.
    assert brief["stands_in_for"] == "Ana Ruiz"
    assert brief["missing"] == "Ana Ruiz"
    # And the urgency is said, not left as an enum nobody reads aloud.
    assert brief["urgency_said"] == "hoy, antes de que se acabe el día"


def test_somebody_elses_words_beat_the_routes_stock_sentence(accounts_db):
    """A route's detail is true of every absence; this call is about one."""
    from agent.accounts.directory import cover_brief

    told = "Hugo está de vacaciones y el martes hay ocho pacientes sin médico"
    brief = cover_brief(DEFAULT_ORG_ID, "provider_on_leave", situation=told)

    assert brief["situation"] == told


def test_the_prompt_renders_the_profile(accounts_db):
    """The brief is worth nothing if it does not reach the prompt."""
    from agent.accounts.directory import cover_brief
    from agent.voice.pipeline import system_prompt_for

    # Built outside the class body: inside one, `cover_brief = cover_brief(...)`
    # shadows the name before the call is made and the lookup skips the
    # enclosing function entirely.
    built = cover_brief(
        DEFAULT_ORG_ID, "provider_on_leave", who="Bea Lis", situation="Ana está de baja"
    )

    class Ctx:
        cover_brief = built

    rendered = system_prompt_for(Ctx())
    assert "Qué hace en la clínica" in rendered
    assert "La situación, en concreto: Ana está de baja" in rendered


# ---- no todas las llamadas salientes son la misma llamada ------------------
def test_an_emergency_is_not_a_favour_being_asked():
    """Todas usaban el guion de "¿te ves cubriéndolo?", incluida ésta."""
    from agent.accounts.directory import cover_brief

    brief = cover_brief(DEFAULT_ORG_ID, "medical_emergency")

    assert "urgencia médica" in brief["purpose"]
    assert "Ni bromas" in brief["purpose"]


def test_the_role_decides_over_the_reason(accounts_db):
    """Un médico de guardia lo es le llames por lo que le llames."""
    from agent.accounts.directory import cover_brief
    from agent.accounts.store import Person, Store

    Store(accounts_db).upsert_person(
        DEFAULT_ORG_ID, Person(slug="on_call", name="Guardia", role="Guardia")
    )

    brief = cover_brief(DEFAULT_ORG_ID, "provider_on_leave", person_slug="on_call")

    assert "de guardia" in brief["purpose"]
    assert "cubra una agenda" in brief["purpose"]


def test_the_purpose_outranks_the_tone_in_the_prompt(accounts_db):
    """Va arriba y lo dice: manda sobre lo que acaba de pedir COVER_PROMPT."""
    from agent.accounts.directory import cover_brief
    from agent.voice.pipeline import system_prompt_for

    built = cover_brief(DEFAULT_ORG_ID, "medical_emergency")

    class Ctx:
        cover_brief = built

    rendered = system_prompt_for(Ctx())
    assert "PARA QUÉ LLAMAS, y esto manda sobre todo lo anterior:" in rendered
    assert rendered.index("PARA QUÉ LLAMAS") < rendered.index("LO QUE HA PASADO")
