"""Metrics must never lie in the direction that flatters a candidate.

The two ways a metric lies: showing `0` where the data does not exist (unknown
cost read as free calls), and counting a rig failure as a model failure. Both
are pinned here, plus the arithmetic of the aggregates, with synthetic cases.
"""
from __future__ import annotations

from evaluator.models import CaseResult
from evaluator.report.metrics import NA, candidate_metrics, summarize


def _case(
    candidate: str = "a",
    scenario_id: str = "sb-001",
    *,
    verdict: str = "pass",
    problem_id: str = "simple_booking",
    repetition: int = 0,
    latencies: list[float] | None = None,
    first_audio: float | None = None,
    submitted: list[dict] | None = None,
    attempts: list[dict] | None = None,
    cost: float | None = None,
    duration: float = 0.0,
    errors: list[str] | None = None,
) -> CaseResult:
    return CaseResult(
        case_id=f"{candidate}/{scenario_id}/r{repetition}",
        call_id=f"call-{candidate}-{scenario_id}-{repetition}",
        scenario_id=scenario_id,
        problem_id=problem_id,
        candidate=candidate,
        repetition=repetition,
        verdict=verdict,
        turn_latencies_ms=latencies or [],
        first_audio_ms=first_audio,
        submitted=submitted or [],
        submit_attempts=attempts or [],
        cost=cost,
        duration_s=duration,
        errors=errors or [],
    )


class TestRates:
    def test_counts_are_paired_with_their_denominator(self):
        cases = [_case(verdict="pass"), _case(verdict="fail"), _case(verdict="fail")]
        metrics = candidate_metrics(cases)
        assert metrics["pass_rate"]["value"] == "33% (1/3)"
        assert metrics["pass_rate"]["numerator"] == 1
        assert metrics["pass_rate"]["denominator"] == 3
        assert metrics["cases"]["value"] == "3"

    def test_an_invalid_case_is_not_a_model_failure(self):
        cases = [
            _case(verdict="fail", repetition=0),
            _case(verdict="invalid_evaluation", repetition=1),
        ]
        metrics = candidate_metrics(cases)
        assert metrics["invalid"]["value"] == "1"
        assert metrics["model_failures"]["value"] == "1"
        # The pass rate is computed over the cases that could be scored at all.
        assert metrics["pass_rate"]["denominator"] == 1

    def test_errors_are_reported_and_not_fatal(self):
        cases = [_case(), _case(errors=["candidate never answered: boom"])]
        metrics = candidate_metrics(cases)
        assert metrics["without_errors"]["value"] == "50% (1/2)"

    def test_empty_input_does_not_crash_and_does_not_invent_zero(self):
        metrics = candidate_metrics([])
        assert metrics["pass_rate"]["value"] == NA
        assert metrics["first_audio_p50"]["value"] == NA
        assert metrics["cost_total"]["value"] == NA


class TestLatencyAndTurns:
    def test_percentiles_come_from_the_measured_turns(self):
        cases = [
            _case(latencies=[100, 200], first_audio=900),
            _case(latencies=[300], first_audio=1100, repetition=1),
        ]
        metrics = candidate_metrics(cases)
        assert metrics["turn_latency_p50"]["value"] == "200 ms"
        assert metrics["turn_latency_p95"]["value"] == "290 ms"
        assert metrics["first_audio_p50"]["value"] == "1000 ms"
        assert metrics["first_audio_p95"]["value"] == "1090 ms"
        assert metrics["turns_median"]["value"] == "2"

    def test_an_unanswered_turn_is_absent_not_a_zero_latency(self):
        # The runner drops unanswered turns before building the case, so a call
        # with one answer and one silence carries a single latency. The metric
        # must average over what was measured, never pad with a zero.
        cases = [_case(latencies=[100])]
        metrics = candidate_metrics(cases)
        assert metrics["turn_latency_p50"]["value"] == "100 ms"
        assert metrics["turn_latency_p50"]["denominator"] == 1
        assert metrics["turn_latency_p95"]["value"] == "100 ms"

    def test_latency_without_measurements_reads_na(self):
        metrics = candidate_metrics([_case()])
        assert metrics["first_audio_p50"]["value"] == NA
        assert metrics["turns_median"]["value"] == NA


class TestSubmissionsAndCost:
    def test_rejections_are_grouped_by_status(self):
        cases = [
            _case(
                attempts=[
                    {"status": 200},
                    {"status": 422},
                    {"status": 409},
                    {"status": 422},
                ],
                submitted=[{"action": "BOOK"}],
            )
        ]
        metrics = candidate_metrics(cases)
        assert metrics["submissions_accepted"]["value"] == "1"
        assert metrics["submissions_rejected"] == {"409": 1, "422": 2}

    def test_unknown_cost_is_unknown_not_zero(self):
        cases = [_case(cost=None), _case(cost=0.25, repetition=1)]
        metrics = candidate_metrics(cases)
        assert metrics["cost_total"]["value"] == NA
        assert metrics["cost_total"]["numerator"] is None

    def test_cost_totals_when_every_call_reported_one(self):
        cases = [_case(cost=0.25), _case(cost=0.25, repetition=1)]
        metrics = candidate_metrics(cases)
        assert metrics["cost_total"]["value"] == "0.5000"

    def test_duration_median(self):
        cases = [_case(duration=10), _case(duration=30, repetition=1)]
        assert candidate_metrics(cases)["duration_p50"]["value"] == "20 s"


class TestStability:
    def test_a_single_repetition_cannot_claim_stability(self):
        assert candidate_metrics([_case()])["stability"]["value"] == NA

    def test_same_verdict_across_repetitions_is_stable(self):
        cases = [_case(repetition=0), _case(repetition=1)]
        assert candidate_metrics(cases)["stability"]["value"] == "100% (2/2)"

    def test_a_flip_between_repetitions_lowers_stability(self):
        cases = [_case(repetition=0), _case(verdict="fail", repetition=1)]
        assert candidate_metrics(cases)["stability"]["value"] == "50% (1/2)"


class TestSummarize:
    def test_per_candidate_and_matrix_are_grouped(self):
        cases = [
            _case(candidate="a", scenario_id="sb-001", problem_id="simple_booking"),
            _case(candidate="b", scenario_id="sb-001", verdict="fail", problem_id="simple_booking"),
            _case(candidate="a", scenario_id="ns-001", problem_id="nearest_site"),
        ]
        summary = summarize(cases)
        assert sorted(summary["candidates"]) == ["a", "b"]
        assert summary["candidates"]["a"]["pass_rate"]["value"] == "100% (2/2)"
        assert summary["candidates"]["b"]["pass_rate"]["value"] == "0% (0/1)"
        assert sorted(summary["problems"]) == ["nearest_site", "simple_booking"]
        assert summary["matrix"]["simple_booking"]["a"] == {"passed": 1, "valid": 1, "invalid": 0}
        assert summary["matrix"]["simple_booking"]["b"] == {"passed": 0, "valid": 1, "invalid": 0}

    def test_errors_are_collected_for_the_console(self):
        cases = [_case(errors=["candidate never answered: boom"])]
        assert summarize(cases)["errors"] == ["candidate never answered: boom"]

    def test_empty_run_summarizes_to_na(self):
        summary = summarize([])
        assert summary["candidates"] == {}
        assert summary["total"]["pass_rate"]["value"] == NA


class TestErrorsByType:
    def test_each_error_is_bucketed_by_the_layer_that_produced_it(self):
        cases = [
            _case(errors=["turn 1: TTS failed: FileNotFoundError: espeak-ng"]),
            _case(errors=["ConnectionClosed: received 1006", "clinic refused call open: HTTP 500"]),
            _case(errors=["caller-side max_call_s reached"]),
        ]
        bucket = candidate_metrics(cases)["errors_by_type"]
        assert bucket["counts"] == {"clinic": 1, "timeout": 1, "transport": 1, "tts": 1}
        assert bucket["numerator"] == 4  # every error is counted
        assert bucket["denominator"] == 3  # over the cases of the run
        assert bucket["cases_with_errors"] == 3

    def test_an_unrecognised_message_stays_other_instead_of_being_guessed(self):
        bucket = candidate_metrics([_case(errors=["algo rarísimo pasó"])])["errors_by_type"]
        assert bucket["counts"] == {"other": 1}

    def test_no_errors_reads_nd_not_zero(self):
        bucket = candidate_metrics([_case()])["errors_by_type"]
        assert bucket["value"] == NA
        assert bucket["numerator"] == 0
        assert bucket["counts"] == {}


class TestAudio:
    def test_totals_declare_how_many_cases_reported_audio(self):
        cases = [
            _case(),
            _case(repetition=1),
        ]
        cases[0].caller_audio_s, cases[0].agent_audio_s = 12.5, 20.0
        cases[1].caller_audio_s, cases[1].agent_audio_s = 7.5, 20.0
        metrics = candidate_metrics(cases)
        assert metrics["audio_caller_s"]["value"] == "20.0 s"
        assert metrics["audio_caller_s"]["denominator"] == 2
        assert metrics["audio_agent_s"]["value"] == "40.0 s"
        assert metrics["audio_ratio"]["value"] == "0.50"

    def test_audio_without_measurements_is_nd(self):
        metrics = candidate_metrics([_case()])
        assert metrics["audio_caller_s"]["value"] == NA
        assert metrics["audio_ratio"]["value"] == NA

    def test_ratio_is_nd_when_the_agent_sent_nothing(self):
        case = _case()
        case.caller_audio_s, case.agent_audio_s = 5.0, 0.0
        assert candidate_metrics([case])["audio_ratio"]["value"] == NA


class TestInterrupts:
    def test_barge_ins_are_counted_with_their_denominator(self):
        interrupted = _case()
        interrupted.interrupts = [{"turn": 1, "at_ms": 100}]
        cases = [interrupted, _case(repetition=1)]
        metrics = candidate_metrics(cases)
        assert metrics["interrupts_total"]["value"] == "1"
        assert metrics["calls_with_interrupts"]["value"] == "50% (1/2)"


class TestArtifacts:
    def test_write_metrics_round_trips_the_summary(self, tmp_path):
        import json

        from evaluator.report.metrics import write_metrics

        case = _case(verdict="pass", repetition=0)
        path = write_metrics(tmp_path, [case])
        assert path.name == "metrics.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["candidates"]["a"]["pass_rate"]["value"] == "100% (1/1)"
        assert data["total"]["cases"]["value"] == "1"

    def test_format_metrics_shows_value_plus_ratio(self):
        from evaluator.report.metrics import format_metrics

        text = format_metrics(summarize([_case(verdict="pass"), _case(verdict="fail")]))
        assert "[a]" in text
        assert "aciertos" in text
        assert "50% (1/2)" in text

    def test_format_metrics_reports_registered_errors(self):
        from evaluator.report.metrics import format_metrics

        text = format_metrics(summarize([_case(errors=["boom"])]))
        assert "errores registrados:" in text
        assert "- boom" in text
