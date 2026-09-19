"""The run plan: fairness between alternatives, and who a dead candidate blames.

Two things an A/B depends on:

- Interleaving. Running each candidate's block to completion lets a backend
  that drifts during the run favour whoever went last, which is the effect
  being measured.
- Attribution. A candidate the runner started and that never listened is a rig
  failure: its cases are `invalid_evaluation`, never scored against the model.

Neither check starts an agent or touches the network.
"""
from __future__ import annotations

from pathlib import Path

from evaluator.models import CandidateConfig, ExperimentConfig, Scenario
from evaluator.runner.experiment import _not_ready_case, case_plan

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"


def _candidate(name: str, **kwargs) -> CandidateConfig:
    defaults = {"name": name, "ws_url": "ws://127.0.0.1:17860/ws"}
    return CandidateConfig(**{**defaults, **kwargs})


def _scenario(scenario_id: str) -> Scenario:
    """A real scenario file: inventing one would drift from the schema."""
    return Scenario.load(str(SCENARIOS / "simple_booking" / f"{scenario_id}.yaml"))


def _config(candidates: list[CandidateConfig], repetitions: int = 1) -> ExperimentConfig:
    return ExperimentConfig(
        name="plan-test",
        clinic_dataset="../data/clinic_dataset.json",
        repetitions=repetitions,
        candidates=candidates,
        scenarios=["../scenarios/**/*.yaml"],
    )


class TestCasePlan:
    def test_candidate_varies_fastest_so_no_one_goes_last(self):
        config = _config([_candidate("a"), _candidate("b"), _candidate("c")])
        scenarios = [
            (_scenario("sb-001"), Path("s1.yaml")),
            (_scenario("sb-002"), Path("s2.yaml")),
        ]
        order = [(cand.name, scenario.id) for _, scenario, _, cand in case_plan(config, scenarios)]
        assert order == [
            ("a", "sb-001"),
            ("b", "sb-001"),
            ("c", "sb-001"),
            ("a", "sb-002"),
            ("b", "sb-002"),
            ("c", "sb-002"),
        ]

    def test_every_repetition_still_sees_every_candidate(self):
        config = _config([_candidate("a"), _candidate("b")], repetitions=2)
        scenarios = [(_scenario("sb-001"), Path("s1.yaml"))]
        plan = case_plan(config, scenarios)
        assert [(rep, cand.name) for rep, _, _, cand in plan] == [
            (0, "a"),
            (0, "b"),
            (1, "a"),
            (1, "b"),
        ]

    def test_plan_covers_every_combination_exactly_once(self):
        config = _config([_candidate("a"), _candidate("b")], repetitions=2)
        scenarios = [
            (_scenario("sb-001"), Path("s1.yaml")),
            (_scenario("sb-002"), Path("s2.yaml")),
        ]
        keys = {
            (rep, scenario.id, cand.name) for rep, scenario, _, cand in case_plan(config, scenarios)
        }
        assert len(keys) == 2 * 2 * 2


class TestNotReadyCandidate:
    def test_its_cases_are_invalid_and_carry_the_cause(self):
        candidate = _candidate("slow-agent", start_command="sleep 60")
        scenario = _scenario("sb-001")
        case = _not_ready_case(
            candidate, scenario, 0, "slow-agent/sb-001/r0", "never listened on 127.0.0.1:17860"
        )
        assert case.verdict == "invalid_evaluation"
        assert case.categories == ["candidate_not_ready"]
        assert case.errors and "never listened" in case.errors[0]
        assert case.scenario_id == scenario.id
        assert case.problem_id == scenario.problem_id

    def test_a_not_ready_case_is_not_counted_as_a_model_failure(self):
        candidate = _candidate("slow-agent", start_command="sleep 60")
        case = _not_ready_case(candidate, _scenario("sb-001"), 0, "case-id", "boom")
        assert case.passed is False
        assert case.verdict != "fail"
        assert case.failure_signal is None
