"""Observer run builder: audit files → a run the console already understands.

Writes the same three artifacts a synthetic run writes - `manifest.json`,
`cases.jsonl`, `report.html` - plus `real_calls.jsonl` with every observed
call, tagged or not. Tagged calls are scored with the shared comparator and
flow into metrics and the diff like any other case; untagged calls stay out
of `cases.jsonl` so they can never move a pass rate they were never judged.

Transcripts are sensitive: everything lands under `results/`, which Git
ignores, and nothing is copied outside the run directory.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluator.compare import categorize, compare, transcript_leaks
from evaluator.models import CaseResult, FieldDiff
from evaluator.observer.backend_calls import BackendCall, OracleMap, load_backend_calls
from evaluator.report.render import render_report

CANDIDATE_FALLBACK = "backend-real"


def _candidate_name(call: BackendCall) -> str:
    return call.engine or CANDIDATE_FALLBACK


def _transcript_lines(call: BackendCall) -> list[str]:
    lines = []
    if call.caller_text.strip():
        lines.append(f"caller: {call.caller_text.strip()}")
    if call.assistant_text.strip():
        lines.append(f"agente: {call.assistant_text.strip()}")
    return lines


def score_call(call: BackendCall, scenario: Any) -> tuple[CaseResult, list[str]]:
    """Score one tagged call against its scenario. Returns (case, leaks)."""
    comparison = compare(
        call.actions,
        scenario.accepted_outcomes,
        forbidden_actions=scenario.oracle.forbidden_actions,
    )
    leaks: list[str] = []
    leak_check = scenario.leak_check
    if leak_check is not None:
        # The observer has full transcripts, so the problem-14 check that the
        # voice path cannot run is exactly the one it can.
        leaks = transcript_leaks([call.assistant_text], leak_check.national_id, leak_check.phone)

    if leaks:
        verdict, signal = "fail", "transcript_leak"
    elif not call.ended:
        verdict, signal = "invalid_evaluation", None
    elif comparison.passed:
        verdict, signal = "pass", None
    else:
        verdict, signal = "fail", comparison.failure_signal

    categories = [] if verdict == "pass" else categorize(
        comparison, leaks, None, call.submissions
    )
    notes = [
        "llamada real observada del audit del backend; sin audio ni latencias del cable",
    ]
    if call.problems:
        notes.extend(call.problems)
    if not call.ended:
        notes.append("el audit no registra el cierre de la llamada: el veredicto no es fiable")

    case = CaseResult(
        case_id=f"{_candidate_name(call)}/{scenario.id}/obs-{call.call_id[:8]}",
        call_id=call.call_id,
        scenario_id=scenario.id,
        problem_id=scenario.problem_id,
        candidate=_candidate_name(call),
        repetition=0,
        verdict=verdict,
        failure_signal=signal,
        categories=categories,
        matched_outcome=comparison.matched_outcome,
        field_diffs=[FieldDiff(**d.model_dump()) for d in comparison.field_diffs],
        extra_actions=comparison.extra_actions,
        missing_actions=comparison.missing_actions,
        submitted=call.actions,
        submit_attempts=call.submissions,
        transcript=_transcript_lines(call),
        duration_s=call.elapsed_s or 0.0,
        notes=notes,
    )
    if leak_check is None:
        case.checks_not_run.append("leak_check")
    if leaks:
        case.notes.append(f"fuga detectada en el transcript del agente: {', '.join(leaks)}")
    return case, leaks


def _real_call_row(
    call: BackendCall,
    scenario_id: str | None,
    case: CaseResult | None,
    leaks: list[str],
) -> dict[str, Any]:
    return {
        "call_id": call.call_id,
        "engine": call.engine,
        "from_number": call.from_number,
        "started_at": call.started_at,
        "last_event_at": call.last_event_at,
        "ended": call.ended,
        "elapsed_s": call.elapsed_s,
        "identity_patient_id": call.identity_patient_id,
        "caller_chars": call.caller_chars,
        "assistant_chars": call.assistant_chars,
        "actions": call.actions,
        "submissions": call.submissions,
        "tagged_scenario": scenario_id,
        "verdict": case.verdict if case else None,
        "leaks": leaks,
        "problems": call.problems,
        "transcript": {"caller": call.caller_text, "assistant": call.assistant_text},
    }


def observe(
    data_dir: Path | str,
    oracle_map: Path | str | None,
    out_root: Path | str,
    run_id: str | None = None,
) -> Path:
    """Build one observer run from the backend's call audits.

    Returns the run directory. The run contains `cases.jsonl` (tagged, scored
    calls only), `real_calls.jsonl` (every call, tagged or not) and a report.
    """
    calls = load_backend_calls(data_dir)
    if not calls:
        raise FileNotFoundError(f"no se encontró ninguna llamada en {data_dir}")
    mapping = OracleMap(oracle_map) if oracle_map else None

    run_id = run_id or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    out_dir = Path(out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    cases: list[CaseResult] = []
    rows: list[dict[str, Any]] = []
    for call in calls:
        matched = mapping.scenario_for(call.call_id) if mapping else None
        scenario = matched[1] if matched else None
        case, leaks = None, []
        if scenario is not None:
            case, leaks = score_call(call, scenario)
            cases.append(case)
        rows.append(_real_call_row(call, scenario.id if scenario else None, case, leaks))

    candidates = sorted({_candidate_name(c) for c in calls})
    engines = {c.engine for c in calls if c.engine}
    # A real digest over what was observed, so two observer runs of the same
    # audit are comparable and a changed audit produces a different hash.
    digest = hashlib.sha256()
    for call in calls:
        digest.update(call.path.name.encode())
        digest.update(call.path.read_bytes())
    manifest = {
        "run_id": run_id,
        "experiment": "backend-observe",
        "rules_version": "scoring-2.0-draft",
        "dataset": "backend-audit",
        "dataset_hash": digest.hexdigest()[:16],
        "dataset_profile": {
            "name": f"audit del backend ({len(calls)} llamadas reales)",
            "counts": {"calls": len(calls), "tagged": len(cases), "untagged": len(calls) - len(cases)},
            "engines": sorted(engines) if engines else ["n/d"],
            "note": "llamadas reales registradas por el backend en DATA_DIR/calls; sin cambiar el backend",
        },
        "repetitions": 1,
        "started_at": min((c.started_at for c in calls if c.started_at), default=None),
        "candidates": [{"name": name, "kind": "external"} for name in candidates],
        "note": "observación post-hoc: los veredictos solo cubren llamadas etiquetadas en el mapa de oráculos",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with open(out_dir / "cases.jsonl", "w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(case.model_dump_json() + "\n")
    with open(out_dir / "real_calls.jsonl", "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)

    render_report(out_dir)
    return out_dir
