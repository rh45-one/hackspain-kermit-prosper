"""Scenario/fixture validation: an incoherent scenario is an evaluator bug."""
from __future__ import annotations

from pathlib import Path

from evaluator.clinic.dataset import Dataset
from evaluator.models import Scenario
from evaluator.runner.experiment import validate_scenario

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"
SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"


def dataset() -> Dataset:
    return Dataset.load(DATASET)


class TestRealScenarios:
    def test_all_scenarios_resolve(self):
        ds = dataset()
        bad = {}
        for path in sorted(SCENARIOS.rglob("*.yaml")):
            problems = validate_scenario(Scenario.load(str(path)), ds)
            if problems:
                bad[path.name] = problems
        assert not bad, bad


class TestChecks:
    def scenario(self, **overrides) -> Scenario:
        base = {
            "id": "t-001",
            "problem_id": "simple_booking",
            "clinic_fixture": "seed-v1",
            "caller": {"opening": "hola"},
            "oracle": {
                "accepted_outcomes": [
                    {"actions": [{"action": "NO_ACTION", "reason": "no_availability"}]}
                ]
            },
        }
        base.update(overrides)
        return Scenario.model_validate(base)

    def test_fixture_mismatch(self):
        s = self.scenario(clinic_fixture="otra-clinica")
        assert any("clinic_fixture" in p for p in validate_scenario(s, dataset()))

    def test_unknown_patient_flagged(self):
        s = self.scenario(
            oracle={
                "accepted_outcomes": [
                    {
                        "actions": [
                            {
                                "action": "BOOK",
                                "patient_id": "P99999",
                                "provider_id": "PR01",
                                "location_id": "centro",
                                "appointment_type_id": "review",
                                "slot": "2026-09-21T09:00:00+02:00",
                                "policy_id": "sanitas",
                            }
                        ]
                    }
                ]
            }
        )
        assert any("patient_id" in p for p in validate_scenario(s, dataset()))

    def test_slot_outside_calendar_flagged(self):
        s = self.scenario(
            oracle={
                "accepted_outcomes": [
                    {
                        "actions": [
                            {
                                "action": "BOOK",
                                "patient_id": "P00042",
                                "provider_id": "PR01",
                                "location_id": "centro",
                                "appointment_type_id": "review",
                                "slot": "2027-09-21T09:00:00+02:00",
                                "policy_id": "sanitas",
                            }
                        ]
                    }
                ]
            }
        )
        assert any("calendar" in p for p in validate_scenario(s, dataset()))

    def test_bad_check_letter_flagged(self):
        s = self.scenario(
            oracle={
                "accepted_outcomes": [
                    {
                        "actions": [
                            {
                                "action": "REGISTER",
                                "given_name": "X",
                                "first_surname": "Y",
                                "second_surname": "Z",
                                "national_id": "12345678A",
                                "date_of_birth": "1990-01-01",
                                "phone": "600000000",
                                "email": "x@y.z",
                                "insurer": "sanitas",
                            }
                        ]
                    }
                ]
            }
        )
        assert any("national_id" in p for p in validate_scenario(s, dataset()))

    def test_no_opening_and_no_turns_flagged(self):
        s = self.scenario(caller={})
        assert any("nothing to say" in p for p in validate_scenario(s, dataset()))
