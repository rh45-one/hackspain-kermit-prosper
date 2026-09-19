"""Run diff: verdict flips, failure changes, missing cases, latency/cost."""
from __future__ import annotations

import json
from pathlib import Path

from evaluator.report.diff import diff_runs, format_diff


def _case(
    candidate: str = "A",
    scenario_id: str = "sb-001",
    repetition: int = 0,
    verdict: str = "pass",
    failure_signal: str | None = None,
    categories: list[str] | None = None,
    latencies: list[float] | None = None,
    cost: float | None = None,
) -> dict:
    return {
        "case_id": f"{candidate}/{scenario_id}/r{repetition}",
        "call_id": "x",
        "scenario_id": scenario_id,
        "problem_id": "simple_booking",
        "candidate": candidate,
        "repetition": repetition,
        "verdict": verdict,
        "failure_signal": failure_signal,
        "categories": categories or [],
        "turn_latencies_ms": latencies or [],
        "cost": cost,
    }


def _write_run(root: Path, name: str, cases: list[dict]) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"run_id": name, "experiment": name}))
    (d / "cases.jsonl").write_text(
        "\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8"
    )
    return d


class TestDiffRuns:
    def test_newly_passing_and_failing(self, tmp_path):
        a = _write_run(tmp_path, "a", [
            _case(scenario_id="s1", verdict="fail", failure_signal="record_mismatch"),
            _case(scenario_id="s2", verdict="pass"),
            _case(scenario_id="s3", verdict="pass"),
        ])
        b = _write_run(tmp_path, "b", [
            _case(scenario_id="s1", verdict="pass"),
            _case(scenario_id="s2", verdict="fail", failure_signal="missing_record"),
            _case(scenario_id="s3", verdict="pass"),
        ])
        result = diff_runs(a, b)
        s = result.summary()
        assert s["newly_passing"] == 1
        assert s["newly_failing"] == 1
        assert s["unchanged"] == 1
        assert s["passes_a"] == 2 and s["passes_b"] == 2

    def test_changed_failure_same_verdict(self, tmp_path):
        a = _write_run(tmp_path, "a", [
            _case(verdict="fail", failure_signal="missing_record",
                  categories=["submission_error"]),
        ])
        b = _write_run(tmp_path, "b", [
            _case(verdict="fail", failure_signal="record_mismatch",
                  categories=["identity_error"]),
        ])
        result = diff_runs(a, b)
        assert result.summary()["changed_failure"] == 1
        d = result.by_kind("changed_failure")[0]
        assert d.signal_a == "missing_record" and d.signal_b == "record_mismatch"

    def test_verdict_changed_invalid_to_pass(self, tmp_path):
        a = _write_run(tmp_path, "a", [_case(verdict="invalid_evaluation")])
        b = _write_run(tmp_path, "b", [_case(verdict="fail", failure_signal="missing_record")])
        result = diff_runs(a, b)
        assert result.summary()["verdict_changed"] == 1
        assert result.summary()["newly_failing"] == 0  # A was not a pass

    def test_only_in_one_run(self, tmp_path):
        a = _write_run(tmp_path, "a", [_case(scenario_id="s1"), _case(scenario_id="s2")])
        b = _write_run(tmp_path, "b", [_case(scenario_id="s2")])
        result = diff_runs(a, b)
        assert result.summary()["only_in_a"] == 1
        assert result.summary()["cases_compared"] == 1

    def test_latency_and_cost_deltas(self, tmp_path):
        a = _write_run(tmp_path, "a", [
            _case(latencies=[100.0, 200.0], cost=0.01),
        ])
        b = _write_run(tmp_path, "b", [
            _case(latencies=[300.0], cost=0.02),
        ])
        d = diff_runs(a, b).diffs[0]
        assert d.latency_delta_ms == 150.0  # 300 - median(100,200)=150
        assert d.cost_delta == 0.01

    def test_cost_unknown_stays_none(self, tmp_path):
        a = _write_run(tmp_path, "a", [_case(cost=None)])
        b = _write_run(tmp_path, "b", [_case(cost=0.01)])
        assert diff_runs(a, b).diffs[0].cost_delta is None


class TestFormat:
    def test_text_output(self, tmp_path):
        a = _write_run(tmp_path, "a", [_case(verdict="fail")])
        b = _write_run(tmp_path, "b", [_case(verdict="pass")])
        text = format_diff(diff_runs(a, b))
        assert "NUEVOS ACIERTOS" in text
        assert "fail -> pass" in text

    def test_missing_dir_raises(self, tmp_path):
        import pytest

        with pytest.raises(FileNotFoundError):
            diff_runs(tmp_path / "nope", tmp_path)
