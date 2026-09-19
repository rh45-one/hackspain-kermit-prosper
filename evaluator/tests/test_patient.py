"""Rules-based simulated caller: answers only from its facts, never invents."""
from __future__ import annotations

from evaluator.models import Caller, CallerBehavior, Limits
from evaluator.simulator.patient import RulesPatient


def make_patient(**overrides) -> RulesPatient:
    caller = Caller(
        opening="Hola, soy Marta.",
        facts={
            "name": "Marta Ruiz Gómez",
            "national_id": "12345678Z",
            "date_of_birth": "1988-03-14",
            "insurer": "sanitas",
            "wants": "la primera cita en general",
        },
        behavior=CallerBehavior(**overrides),
    )
    return RulesPatient(caller)


class TestFacts:
    def test_answers_name(self):
        p = make_patient()
        assert "Marta" in p.respond("¿Me dice su nombre?")

    def test_answers_national_id(self):
        p = make_patient()
        assert "12345678Z" in p.respond("¿Me puede dar su DNI?")

    def test_answers_dob(self):
        p = make_patient()
        assert "1988" in p.respond("¿Fecha de nacimiento?")

    def test_answers_insurer(self):
        p = make_patient()
        assert "sanitas" in p.respond("¿Qué seguro tiene?")

    def test_never_invents_missing_fact(self):
        p = make_patient()
        # 'email' is not in facts - the caller cannot answer it truthfully.
        p.facts.pop("email", None)
        reply = p.respond("¿Su correo electrónico?")
        assert "@" not in reply
        # It says it does not have it, instead of "¿puede repetirlo?" - the
        # latter is indistinguishable from an agent nobody understands.
        assert "no lo tengo" in reply.lower()
        assert p.log.unanswerable == ["email"]
        assert p.log.missed == []  # a fixture gap is not a misunderstanding

    def test_asks_to_repeat_only_when_it_understood_nothing(self):
        p = make_patient()
        reply = p.respond("Mmm.")
        assert "repetir" in reply
        assert p.log.unanswerable == []

    def test_a_closing_is_not_a_question_about_a_fact(self):
        """"quedado" contains "edad": word boundaries, not substrings."""
        p = make_patient()
        reply = p.respond("Perfecto, ha quedado reservada. ¿Algo más?")
        assert "gracias" in reply.lower()

    def test_accented_question_is_understood(self):
        p = make_patient()
        assert "1988" in p.respond("¿Cuántos años tiene?")


class TestBehavior:
    def test_refuses_identifier_when_configured(self):
        p = make_patient(provide_identifier_when_asked=False)
        reply = p.respond("¿Me da su DNI?")
        assert "12345678Z" not in reply

    def test_reveals_second_policy_only_when_asked(self):
        p = make_patient(reveal_second_policy_when_asked=True)
        p.facts["policies"] = ["dkv", "privado"]
        reply = p.respond("¿Tiene alguna otra póliza o seguro?")
        assert "privado" in reply

    def test_keeps_primary_policy_on_plain_question(self):
        p = make_patient(reveal_second_policy_when_asked=True)
        p.facts["policies"] = ["dkv", "privado"]
        reply = p.respond("¿Qué seguro tiene?")
        assert "dkv" in reply and "privado" in reply  # reveals both once asked

    def test_correction_fires_once(self):
        p = make_patient(corrections=["No, he dicho el diecisiete."])
        assert p.respond("¿Qué día?") == "No, he dicho el diecisiete."
        assert p.respond("¿Me dice su nombre?") != "No, he dicho el diecisiete."

    def test_correction_does_not_preempt_an_answerable_question(self):
        """Answer first: a correction jumping the queue derails identity."""
        p = make_patient(corrections=["No, he dicho el martes."])
        assert "Marta" in p.respond("¿Me dice su nombre?")
        assert "12345678Z" in p.respond("¿Y su DNI?")
        # Still pending, and said before accepting the wrong slot.
        assert p.respond("Puedo ofrecerle el jueves a las 9, ¿le viene?") == (
            "No, he dicho el martes."
        )
        assert "Sí" in p.respond("Entonces el martes a las 17:00, ¿le parece?")


class TestFlow:
    def test_accepts_first_offer(self):
        p = make_patient()
        assert "Sí" in p.respond("Puedo ofrecerle el lunes a las 9, ¿le viene?")

    def test_declines_offer_when_configured(self):
        p = make_patient(accept_first_offer=False)
        p.facts["prefer"] = "por la tarde"
        assert "tarde" in p.respond("Puedo ofrecerle el lunes a las 9, ¿le viene?")

    def test_hangs_up_after_closing(self):
        p = make_patient()
        reply = p.respond("Perfecto, ha quedado reservada. ¿Algo más?")
        assert "gracias" in reply.lower()
        assert p.respond("¿Seguro?") is None

    def test_gives_up_after_repeats(self):
        p = make_patient(max_repeats=2)
        assert "repetir" in p.respond("¿?")
        assert "llamo" in p.respond("¿??")
        assert p.respond("¿???") is None

    def test_opening_returned(self):
        p = make_patient()
        assert p.opening() == "Hola, soy Marta."

    def test_max_turns_guard(self):
        p = RulesPatient(
            Caller(opening="hola", facts={"name": "x"}), Limits(max_turns=1)
        )
        p.respond("¿nombre?")
        assert p.respond("¿nombre?") is None
