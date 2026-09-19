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

import json
import statistics
from pathlib import Path
from typing import Any

from evaluator.models import CaseResult

NA = "n/d"

# Error strings come from several layers (harness, clinic receiver, text
# adapter, TTS subprocess). They are classified by their own words, and a
# message that matches nothing stays `other` instead of being guessed into a
# category: a wrong attribution is worse than an honest bucket.
ERROR_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("timeout", ("max_call_s", "timeout", "timed out")),
    ("tts", ("tts", "espeak", "pico2wave", "synthesis")),
    ("text_adapter", ("text adapter", "/turns")),
    ("clinic", ("clinic", "/availability", "/api/v1")),
    ("submission", ("submit", "record", "flush")),
    ("transport", ("connection", "websocket", "closed", "reset", "eof", "connect")),
    ("stt", ("stt", "deepgram", "transcri")),
)


def classify_error(message: str) -> str:
    """Bucket one error string by the layer it came from (heuristic, declared)."""
    low = message.lower()
    for kind, needles in ERROR_KINDS:
        if any(needle in low for needle in needles):
            return kind
    return "other"


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


def _metric(
    numerator: float | None,
    denominator: float | None,
    text: str,
    kind: str = "value",
) -> dict[str, Any]:
    """One metric: display text plus the numbers behind it.

    `kind` tells the renderers which shape the value has, so a percentile
    (`value`) is never printed with an invented "n/d" ratio the way a count
    or a rate is.
    """
    return {
        "value": text,
        "numerator": numerator,
        "denominator": denominator,
        "kind": kind,
    }


def _count(value: float | None, denominator: float | None) -> dict[str, Any]:
    return _metric(value, denominator, NA if value is None else f"{value:.0f}", kind="count")


def _rate(numerator: int | None, denominator: int | None) -> dict[str, Any]:
    if numerator is None or not denominator:
        return _metric(None, denominator, NA, kind="rate")
    return _metric(
        numerator,
        denominator,
        f"{100 * numerator / denominator:.0f}% ({numerator}/{denominator})",
        kind="rate",
    )


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


def _errors_by_type(cases: list[CaseResult]) -> dict[str, Any]:
    """Count errors by the layer that produced them.

    A rig failure and a model failure must never blend: this table is how a
    developer sees that a run was dominated by the harness (e.g. TTS failing
    to synthesise) instead of by the agent under test.
    """
    counts: dict[str, int] = {}
    total = 0
    with_errors = 0
    for case in cases:
        if case.errors:
            with_errors += 1
        for message in case.errors:
            kind = classify_error(message)
            counts[kind] = counts.get(kind, 0) + 1
            total += 1
    ordered = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    return {
        "value": " · ".join(f"{kind}×{n}" for kind, n in ordered.items()) if ordered else NA,
        "counts": ordered,
        "numerator": total,
        "denominator": len(cases),
        "cases_with_errors": with_errors,
        "kind": "count",
    }


def _audio_seconds(cases: list[CaseResult]) -> tuple[list[float], list[float]]:
    caller = [c.caller_audio_s for c in cases if c.caller_audio_s is not None]
    agent = [c.agent_audio_s for c in cases if c.agent_audio_s is not None]
    return caller, agent


def _audio_metric(values: list[float]) -> dict[str, Any]:
    """Total seconds, declaring how many cases actually reported audio."""
    if not values:
        return _metric(None, 0, NA)
    total = sum(values)
    return _metric(total, len(values), f"{total:.1f} s", kind="count")


def _audio_ratio(cases: list[CaseResult]) -> dict[str, Any]:
    """Caller seconds per agent second: how much the agent talked back."""
    pairs = [
        (c.caller_audio_s, c.agent_audio_s)
        for c in cases
        if c.caller_audio_s is not None and c.agent_audio_s
    ]
    if not pairs:
        return _metric(None, 0, NA)
    caller = sum(pair[0] for pair in pairs)
    agent = sum(pair[1] for pair in pairs)
    ratio = caller / agent if agent else None
    return _metric(ratio, len(pairs), NA if ratio is None else f"{ratio:.2f}")


def _interrupts(cases: list[CaseResult]) -> tuple[int, int]:
    total = sum(len(c.interrupts) for c in cases)
    calls = sum(1 for c in cases if c.interrupts)
    return total, calls


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
    caller_audio, agent_audio = _audio_seconds(cases)
    interrupts_total, calls_with_interrupts = _interrupts(cases)

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
        "errors_by_type": _errors_by_type(cases),
        "audio_caller_s": _audio_metric(caller_audio),
        "audio_agent_s": _audio_metric(agent_audio),
        "audio_ratio": _audio_ratio(cases),
        "interrupts_total": _count(interrupts_total, total),
        "calls_with_interrupts": _rate(calls_with_interrupts, total),
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


def write_metrics(run_dir: Path | str, cases: list[CaseResult]) -> Path:
    """Persist the same aggregates the console shows, for A/B and `diff`."""
    path = Path(run_dir) / "metrics.json"
    path.write_text(json.dumps(summarize(cases), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


_HEADLINE = (
    ("cases", "casos"),
    ("without_errors", "sin errores"),
    ("pass_rate", "aciertos"),
    ("invalid", "no evaluables"),
    ("model_failures", "fallos del modelo"),
    ("first_audio_p50", "primera respuesta p50"),
    ("first_audio_p95", "primera respuesta p95"),
    ("turn_latency_p50", "latencia por turno p50"),
    ("turn_latency_p95", "latencia por turno p95"),
    ("turns_median", "turnos (mediana)"),
    ("submissions_accepted", "submissions aceptadas"),
    ("cost_total", "coste total"),
    ("duration_p50", "duración p50"),
    ("interrupts_total", "barge-ins"),
    ("calls_with_interrupts", "llamadas con barge-in"),
    ("audio_caller_s", "audio del caller"),
    ("audio_agent_s", "audio del agente"),
    ("audio_ratio", "caller/agente"),
    ("errors_by_type", "errores por tipo"),
    ("stability", "estabilidad"),
)


def format_metrics(summary: dict[str, Any]) -> str:
    """Plain-text metric table for the CLI (`evaluator.cli metrics`)."""
    lines: list[str] = []
    for name, metrics in (summary.get("candidates") or {}).items():
        lines.append(f"[{name}]")
        for key, label in _HEADLINE:
            metric = metrics.get(key)
            if metric is None:
                continue
            ratio = ""
            if metric.get("kind") == "count" and metric.get("denominator"):
                ratio = f"  (de {metric['denominator']:g})"
            lines.append(f"  {label:<24} {metric['value']}{ratio}")
        lines.append("")
    errors = summary.get("errors") or []
    if errors:
        lines.append("errores registrados:")
        lines.extend(f"  - {message}" for message in errors)
        lines.append("")
    return "\n".join(lines).rstrip()
