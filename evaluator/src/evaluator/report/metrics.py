"""Run metrics: the aggregates a developer reads before trusting a verdict.

Per-case data already exists in `CaseResult`; this turns a run into the numbers
a person actually asks for - did it finish without errors, how many turns, how
fast the agent answered, what was submitted, what it cost, and how stable the
verdict is across repetitions.

Two rules, both learned the hard way in this codebase:

- A metric with no data reads `n/d`, never `0`. A candidate that never exposed
  cost has unknown cost, not free calls.
- A candidate that never answered (`invalid_evaluation`, `candidate_not_ready`)
  is counted apart from model failures. Counting it as a failure would blame the
  model for an input that never arrived.

Every aggregate exposes its numerator and denominator, so a rate never hides
how many cases it was computed over.
"""
from __future__ import annotations

import statistics
from typing import Any

from evaluator.models import CaseResult

NA = "n/d"


def _percentile(values: list[float], fraction: float) -> float | None:
    """Linear interpolation, mirroring report/render.py so the console and the
    HTML report cannot disagree about the same numbers."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _metric(numerator: float | None, denominator: float | None, text: str) -> dict[str, Any]:
    return {"value": text, "numerator": numerator, "denominator": denominator}


def _count(value: float | None, denominator: float | None) -> dict[str, Any]:
    return _metric(value, denominator, NA if value is None else f"{value:.0f}")


def _rate(numerator: int | None, denominator: int | None) -> dict[str, Any]:
    if numerator is None or not denominator:
        return _metric(None, denominator, NA)
    return _metric(numerator, denominator, f"{100 * numerator / denominator:.0f}% ({numerator}/{denominator})")


def _ms(value: float | None) -> str:
    return NA if value is None else f"{value:.0f} ms"


def _money(value: float | None) -> str:
    return NA if value is None else f"{value:.4f}"


def _latencies(cases: list[CaseResult]) -> list[float]:
    return [ms for case in cases for ms in case.turn_latencies_ms if ms is not None]


def _first_audio(cases: list[CaseResult]) -> list[float]:
    return [case.first_audio_ms for case in cases if case.first_audio_ms is not None]


def _submission_rejections(cases: list[CaseResult]) -> dict[str, int]:
    rejected: dict[str, int] = {}
    for case in cases:
        for attempt in case.submit_attempts:
            status = attempt.get("status")
            if isinstance(status, int) and status != 200:
                key = str(status)
                rejected[key] = rejected.get(key, 0) + 1
    return dict(sorted(rejected.items()))


def _stability(cases: list[CaseResult]) -> dict[str, Any]:
    """Share of repetitions that agree with the majority verdict per scenario."""
    by_scenario: dict[str, list[str]] = {}
    for case in cases:
        by_scenario.setdefault(case.scenario_id, []).append(case.verdict)
    repeated = {sid: verdicts for sid, verdicts in by_scenario.items() if len(verdicts) > 1}
    if not repeated:
        return _metric(None, None, NA)
    agree = 0
    total = 0
    for verdicts in repeated.values():
        majority = max(set(verdicts), key=verdicts.count)
        agree += verdicts.count(majority)
        total += len(verdicts)
    return _rate(agree, total)


def candidate_metrics(cases: list[CaseResult]) -> dict[str, Any]:
    """The metric table for one candidate (or for the whole run)."""
    total = len(cases)
    valid = [case for case in cases if case.verdict != "invalid_evaluation"]
    passed = sum(1 for case in valid if case.verdict == "pass")
    invalid = total - len(valid)
    without_errors = sum(1 for case in cases if not case.errors)
    latencies = _latencies(cases)
    first_audio = _first_audio(cases)
    costs = [case.cost for case in cases]
    known_costs = [c for c in costs if c is not None]
    turns = [len(case.turn_latencies_ms) for case in cases if case.turn_latencies_ms]
    submitted = sum(len(case.submitted) for case in cases)
    attempts = sum(len(case.submit_attempts) for case in cases)
    durations = [case.duration_s for case in cases if case.duration_s]

    return {
        "cases": _count(total, total),
        "without_errors": _rate(without_errors, total),
        "invalid": _count(invalid, total),
        "model_failures": _count(len(valid) - passed, len(valid)),
        "pass_rate": _rate(passed, len(valid)),
        "turns_median": _metric(
            statistics.median(turns) if turns else None,
            len(turns),
            NA if not turns else f"{statistics.median(turns):.0f}",
        ),
        "first_audio_p50": _metric(
            _percentile(first_audio, 0.5),
            len(first_audio),
            _ms(_percentile(first_audio, 0.5)),
        ),
        "first_audio_p95": _metric(
            _percentile(first_audio, 0.95),
            len(first_audio),
            _ms(_percentile(first_audio, 0.95)),
        ),
        "turn_latency_p50": _metric(
            _percentile(latencies, 0.5), len(latencies), _ms(_percentile(latencies, 0.5))
        ),
        "turn_latency_p95": _metric(
            _percentile(latencies, 0.95), len(latencies), _ms(_percentile(latencies, 0.95))
        ),
        "submissions_accepted": _count(submitted, attempts or total),
        "submissions_rejected": _submission_rejections(cases),
        "cost_total": _metric(
            sum(known_costs) if len(known_costs) == total and total else None,
            total,
            _money(sum(known_costs)) if len(known_costs) == total and total else NA,
        ),
        "duration_p50": _metric(
            statistics.median(durations) if durations else None,
            len(durations),
            NA if not durations else f"{statistics.median(durations):.0f} s",
        ),
        "stability": _stability(cases),
    }


def summarize(cases: list[CaseResult]) -> dict[str, Any]:
    """Everything the developer console shows for one run."""
    candidates = sorted({case.candidate for case in cases})
    problems = sorted({case.problem_id for case in cases})
    per_candidate: dict[str, Any] = {}
    matrix: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        own = [case for case in cases if case.candidate == candidate]
        per_candidate[candidate] = candidate_metrics(own)
        for problem in problems:
            of_problem = [case for case in own if case.problem_id == problem]
            if not of_problem:
                continue
            valid = [case for case in of_problem if case.verdict != "invalid_evaluation"]
            matrix.setdefault(problem, {})[candidate] = {
                "passed": sum(1 for case in valid if case.verdict == "pass"),
                "valid": len(valid),
                "invalid": len(of_problem) - len(valid),
            }
    return {
        "total": candidate_metrics(cases),
        "candidates": per_candidate,
        "problems": problems,
        "matrix": matrix,
        "errors": sorted({message for case in cases for message in case.errors}),
    }
