"""Side-by-side across candidates: the A/B view the runner already has the data for.

Every case carries its candidate, so the comparison is a rendering of one run
rather than a new run. These tests pin the grouping, the disagreement marker
and the totals, with a synthetic run directory - no agent, no network.
"""
from __future__ import annotations

import json

import pytest

from evaluator.models import CaseResult
from evaluator.report.side_by_side import (
    format_side_by_side,
    load_cases,
    median_latency,
    side_by_side,
    side_by_side_json,
)

RUN = "20260919T170000Z-abc123"


def _case(
    candidate: str,
    scenario_id: str,
    verdict: str,
    *,
    repetition: int = 0,
    signal: str | None = None,
    latencies: list[float] | None = None,
    errors: list[str] | None = None,
    submitted: list[dict] | None = None,
) -> CaseResult:
    return CaseResult(
        case_id=f"{candidate}/{scenario_id}/r{repetition}",
        call_id=f"call-{candidate}-{scenario_id}",
        scenario_id=scenario_id,
        problem_id="simple_booking",
        candidate=candidate,
        repetition=repetition,
        verdict=verdict,
        failure_signal=signal,
        turn_latencies_ms=latencies or [],
        errors=errors or [],
        submitted=submitted or [],
    )


@pytest.fixture
def run_dir(tmp_path):
    directory = tmp_path / RUN
    directory.mkdir()
    cases = [
        _case("baseline", "sb-001", "pass", latencies=[100, 200]),
        _case("candidate", "sb-001", "fail", signal="record_mismatch", latencies=[150, 250]),
        _case("baseline", "sb-002", "pass"),
        _case("candidate", "sb-002", "pass"),
        _case("baseline", "ns-001", "invalid_evaluation", errors=["candidate never answered"]),
        _case("candidate", "ns-001", "pass"),
    ]
    (directory / "cases.jsonl").write_text(
        "".join(case.model_dump_json() + "\n" for case in cases), encoding="utf-8"
    )
    return directory


def test_missing_run_directory_says_so(tmp_path):
    with pytest.raises(FileNotFoundError) as error:
        load_cases(tmp_path / "nope")
    assert "cases.jsonl" in str(error.value)


def test_rows_are_scenario_and_repetition_columns_are_candidates(run_dir):
    result = side_by_side(run_dir)
    assert result.candidates == ["baseline", "candidate"]
    assert [(row.scenario_id, row.repetition) for row in result.rows] == [
        ("ns-001", 0),
        ("sb-001", 0),
        ("sb-002", 0),
    ]


def test_disagreements_are_the_rows_that_matter(run_dir):
    result = side_by_side(run_dir)
    flagged = [(row.scenario_id, row.verdicts) for row in result.disagreements()]
    assert flagged == [("ns-001", {"invalid_evaluation", "pass"}), ("sb-001", {"fail", "pass"})]
    assert result.summary()["disagreements"] == 2


def test_a_row_without_a_candidate_is_not_an_error(tmp_path):
    directory = tmp_path / "partial"
    directory.mkdir()
    only = _case("baseline", "sb-001", "pass")
    (directory / "cases.jsonl").write_text(only.model_dump_json() + "\n", encoding="utf-8")
    result = side_by_side(directory)
    assert result.candidates == ["baseline"]
    assert result.rows[0].cell_text("baseline") == "PASA"
    assert result.rows[0].disagrees is False


def test_cell_text_shows_signal_and_median_latency(run_dir):
    row = side_by_side(run_dir).rows[1]
    assert row.scenario_id == "sb-001"
    assert row.cell_text("baseline") == "PASA 150ms"
    assert row.cell_text("candidate") == "FALLA:record_mismatch 200ms"
    assert row.cell_text("missing-candidate") == "—"


def test_median_latency_is_none_without_measurements():
    assert median_latency(_case("a", "sb-001", "pass")) is None
    assert median_latency(_case("a", "sb-001", "pass", latencies=[10, 30, 20])) == 20


def test_format_marks_disagreements_and_totals(run_dir):
    text = format_side_by_side(side_by_side(run_dir))
    assert "baseline" in text and "candidate" in text
    assert "desacuerdos: 2" in text
    assert "sb-001" in text and "FALLA:record_mismatch" in text
    assert "inválidas 1" in text  # the baseline's invalid case
    assert "con errores 1" in text


def test_empty_run_is_reported_not_crashed(tmp_path):
    directory = tmp_path / "empty"
    directory.mkdir()
    (directory / "cases.jsonl").write_text("", encoding="utf-8")
    result = side_by_side(directory)
    assert result.rows == []
    assert "(sin casos)" in format_side_by_side(result)


def test_format_keeps_columns_apart_with_long_signals(tmp_path):
    directory = tmp_path / "long"
    directory.mkdir()
    cases = [
        _case("a", "sb-001", "fail", signal="missing_record"),
        _case("b", "sb-001", "fail", signal="record_mismatch"),
    ]
    (directory / "cases.jsonl").write_text(
        "".join(case.model_dump_json() + "\n" for case in cases), encoding="utf-8"
    )
    lines = format_side_by_side(side_by_side(directory)).splitlines()
    row = next(line for line in lines if line.startswith("sb-001"))
    assert "FALLA:missing_record" in row and "FALLA:record_mismatch" in row
    assert "FALLA:missing_record " in row  # padding survived the long cell


def test_json_summary_is_machine_readable(run_dir):
    payload = json.loads(side_by_side_json(side_by_side(run_dir)))
    assert payload["candidates"] == ["baseline", "candidate"]
    assert payload["rows"] == 3
    assert payload["disagreements"] == 2
    assert payload["per_candidate"]["candidate"]["pass"] == 2
    assert payload["per_candidate"]["baseline"]["invalid_evaluation"] == 1
