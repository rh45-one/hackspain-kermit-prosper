"""Restricted-LLM patient: facts-only prompting and rules fallback."""
from __future__ import annotations

import httpx
import pytest

from evaluator.models import Caller, CallerBehavior, Limits, LLMConfig
from evaluator.simulator.llm_patient import LLMPatient, make_patient
from evaluator.simulator.patient import RulesPatient


def _caller(**kw) -> Caller:
    return Caller(
        opening="Hola, soy Marta.",
        facts={
            "name": "Marta Ruiz",
            "national_id": "12345678Z",
            "wants": "la primera cita",
        },
        llm=LLMConfig(**kw),
    )


class TestFallback:
    def test_unreachable_provider_falls_back(self):
        # No LLM server is listening; the patient must degrade to rules,
        # not crash - an LLM outage is not an agent failure.
        patient = LLMPatient(_caller(endpoint="http://127.0.0.1:1/v1/chat/completions"),
                             timeout_s=0.5)
        reply = patient.respond("¿Me dice su nombre?")
        assert patient.fell_back
        assert "Marta" in reply  # rules patient still answers from facts

    def test_stays_on_fallback(self):
        patient = LLMPatient(_caller(endpoint="http://127.0.0.1:1/v1/chat/completions"),
                             timeout_s=0.5)
        patient.respond("hola")
        patient.respond("adiós")
        assert patient.fell_back

    def test_malformed_response_falls_back(self, monkeypatch):
        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def post(self, *a, **k):
                class R:
                    status_code = 200

                    def raise_for_status(self):
                        pass

                    def json(self):
                        return {"choices": [{"message": {"content": ""}}]}

                return R()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        patient = LLMPatient(_caller())
        reply = patient.respond("¿Me dice su nombre?")
        assert patient.fell_back
        assert "Marta" in reply


class TestOracleIsolation:
    def test_prompt_has_facts_not_outcomes(self, monkeypatch):
        sent = {}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def post(self, url, json=None, headers=None):
                sent["payload"] = json

                class R:
                    def raise_for_status(self):
                        pass

                    def json(self):
                        return {"choices": [{"message": {"content": "Me llamo Marta."}}]}

                return R()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        patient = LLMPatient(_caller())
        patient.respond("¿Su nombre?")

        system = sent["payload"]["messages"][0]["content"]
        # Facts are in the prompt; oracle-shaped content must never be.
        assert "Marta Ruiz" in system
        assert "12345678Z" in system
        for forbidden in ("BOOK", "accepted", "oracle", "appointment_type_id"):
            assert forbidden not in system


class TestBehaviourInPrompt:
    def test_corrections_and_policy_rules_present(self, monkeypatch):
        sent = {}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def post(self, url, json=None, headers=None):
                sent["payload"] = json

                class R:
                    def raise_for_status(self):
                        pass

                    def json(self):
                        return {"choices": [{"message": {"content": "vale"}}]}

                return R()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        caller = _caller()
        caller.behavior = CallerBehavior(
            corrections=["Me corrijo: era el lunes."],
            reveal_second_policy_when_asked=True,
        )
        patient = LLMPatient(caller)
        patient.respond("hola")
        system = sent["payload"]["messages"][0]["content"]
        assert "Me corrijo: era el lunes." in system
        assert "pólizas" in system


class TestFactory:
    def test_rules_when_no_llm(self):
        caller = Caller(opening="hola", facts={"name": "X"})
        assert isinstance(make_patient(caller, Limits()), RulesPatient)

    def test_llm_when_configured(self):
        assert isinstance(make_patient(_caller(), Limits()), LLMPatient)

    def test_requires_llm_config(self):
        with pytest.raises(ValueError, match="caller.llm"):
            LLMPatient(Caller(opening="hola"))


class TestClosesLikeRules:
    def test_max_turns_stops(self, monkeypatch):
        patient = LLMPatient(_caller(endpoint="http://127.0.0.1:1/"), timeout_s=0.3,
                             limits=Limits(max_turns=2))
        patient.respond("a")
        patient.respond("b")
        assert patient.respond("c") is None
