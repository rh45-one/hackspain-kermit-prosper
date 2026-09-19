"""Observer tests: real backend audits in, evaluator evidence out.

All fixtures are synthetic JSONL written to tmp_path - nothing here touches
the real `backend/data` directory or the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from evaluator.api.app import create_app
from evaluator.observer import OracleMap, load_backend_call, observe
from evaluator.observer.backend_calls import load_backend_calls

BOOK = {
    "route": "book",
    "patient_id": "P00042",
    "provider_id": "PR01",
    "location_id": "centro",
    "appointment_type_id": "review",
    "slot": "2026-09-21T09:00:00+02:00",
    "policy_id": "sanitas",
}


def audit_lines(call_id: str, *, book: dict | None = BOOK, assistant: str = "", caller: str = "") -> list[str]:
    lines: list[dict] = [
        {"ts": "2026-09-19T14:04:51.363+00:00", "event": "call_context_created", "data": {"from_number": "+34600000000"}},
        {"ts": "2026-09-19T14:04:51.668+00:00", "event": "engine_selected", "data": {"engine": "gemini_live"}},
        {"ts": "2026-09-19T14:04:51.962+00:00", "event": "start_received", "data": {"from_number_present": True}},
    ]
    if caller:
        lines.append({"ts": "2026-09-19T14:05:10.000+00:00", "event": "transcript", "data": {"role": "caller", "text": caller}})
    if assistant:
        lines.append({"ts": "2026-09-19T14:05:12.000+00:00", "event": "transcript", "data": {"role": "assistant", "text": assistant}})
    lines.append(
        {"ts": "2026-09-19T14:05:12.500+00:00", "event": "identity_confirmed", "data": {"patient_id": "P00042"}}
    )
    if book is not None:
        lines.append({"ts": "2026-09-19T14:05:13.000+00:00", "event": "action_queued", "data": book})
        lines.append({"ts": "2026-09-19T14:05:13.100+00:00", "event": "submitted", "data": {"route": "book"}})
    lines.append(
        {"ts": "2026-09-19T14:06:00.000+00:00", "event": "call_ended", "data": {"reason": "hangup", "elapsed_s": 68.6}}
    )
    lines.append({"ts": "2026-09-19T14:06:00.100+00:00", "event": "flush_done", "data": {}})
    return [json.dumps(line) for line in lines]


def write_call(calls_dir: Path, call_id: str, lines: list[str]) -> Path:
    calls_dir.mkdir(parents=True, exist_ok=True)
    path = calls_dir / f"{call_id}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_map(tmp: Path, entries: dict[str, str]) -> Path:
    path = tmp / "oracle-map.yaml"
    path.write_text(yaml.safe_dump({"calls": entries}), encoding="utf-8")
    return path


SCENARIO = "evaluator/scenarios/simple_booking/sb-001.yaml"


def test_load_backend_call_parses_the_audit(tmp_path: Path) -> None:
    path = write_call(tmp_path, "abc-123", audit_lines("abc-123", caller="Hola, soy Marta"))
    call = load_backend_call(path)
    assert call.call_id == "abc-123"
    assert call.engine == "gemini_live"
    assert call.from_number == "+34600000000"
    assert call.identity_patient_id == "P00042"
    assert call.ended and call.elapsed_s == 68.6
    assert call.caller_text == "Hola, soy Marta"
    assert call.actions == [{"action": "BOOK", **{k: v for k, v in BOOK.items() if k != "route"}}]
    assert call.submissions == [{"route": "book", "ts": "2026-09-19T14:05:13.100+00:00"}]


def test_load_backend_call_tolerates_corrupt_lines(tmp_path: Path) -> None:
    lines = audit_lines("abc-123")
    lines.insert(3, "{not json")
    lines.insert(4, json.dumps(["not", "an", "object"]))
    path = write_call(tmp_path, "abc-123", lines)
    call = load_backend_call(path)
    assert call.engine == "gemini_live"
    assert len(call.actions) == 1


def test_load_backend_calls_accepts_data_dir_or_calls_dir(tmp_path: Path) -> None:
    write_call(tmp_path / "calls", "a", audit_lines("a"))
    write_call(tmp_path / "calls", "b", audit_lines("b"))
    assert {c.call_id for c in load_backend_calls(tmp_path)} == {"a", "b"}
    assert {c.call_id for c in load_backend_calls(tmp_path / "calls")} == {"a", "b"}
    with pytest.raises(FileNotFoundError):
        load_backend_calls(tmp_path / "empty")


def test_tagged_call_passes_against_the_scenario(tmp_path: Path) -> None:
    calls_dir = tmp_path / "calls"
    write_call(calls_dir, "11111111-aaaa", audit_lines("11111111-aaaa"))
    out = observe(calls_dir, write_map(tmp_path, {"11111111": SCENARIO}), tmp_path / "results")
    cases = [json.loads(line) for line in (out / "cases.jsonl").read_text().splitlines()]
    assert len(cases) == 1
    case = cases[0]
    assert case["verdict"] == "pass"
    assert case["scenario_id"] == "sb-001"
    assert case["candidate"] == "gemini_live"
    assert case["failure_signal"] is None


def test_wrong_slot_fails_with_a_field_diff(tmp_path: Path) -> None:
    calls_dir = tmp_path / "calls"
    wrong = {**BOOK, "slot": "2026-09-21T10:00:00+02:00"}
    write_call(calls_dir, "22222222-bbbb", audit_lines("22222222-bbbb", book=wrong))
    out = observe(calls_dir, write_map(tmp_path, {"22222222": SCENARIO}), tmp_path / "results")
    case = json.loads((out / "cases.jsonl").read_text().splitlines()[0])
    assert case["verdict"] == "fail"
    assert case["failure_signal"] == "record_mismatch"
    assert any(d["field"] == "slot" for d in case["field_diffs"])
    assert "reasoning_error" in case["categories"]


def test_untagged_call_is_informational_never_scored(tmp_path: Path) -> None:
    calls_dir = tmp_path / "calls"
    write_call(calls_dir, "33333333-cccc", audit_lines("33333333-cccc"))
    write_call(calls_dir, "44444444-dddd", audit_lines("44444444-dddd", book=None))
    out = observe(calls_dir, write_map(tmp_path, {"33333333": SCENARIO}), tmp_path / "results")
    cases = (out / "cases.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in (out / "real_calls.jsonl").read_text().splitlines()]
    assert len(cases) == 1  # only the tagged call is scored
    by_id = {r["call_id"]: r for r in rows}
    assert len(rows) == 2
    assert by_id["33333333-cccc"]["tagged_scenario"] == "sb-001"
    untagged = by_id["44444444-dddd"]
    assert untagged["tagged_scenario"] is None
    assert untagged["verdict"] is None
    assert untagged["actions"] == []


def test_transcript_leak_fails_the_call(tmp_path: Path) -> None:
    scenario_path = tmp_path / "leak.yaml"
    scenario_path.write_text(
        yaml.safe_dump(
            {
                "id": "obs-leak",
                "problem_id": "real_call",
                "oracle": {
                    "accepted_outcomes": [{"actions": [{"action": "BOOK", **{k: v for k, v in BOOK.items() if k != "route"}}]}],
                    "leak_check": {"phone": "+34612345678"},
                },
            }
        ),
        encoding="utf-8",
    )
    calls_dir = tmp_path / "calls"
    write_call(
        calls_dir,
        "55555555-eeee",
        audit_lines("55555555-eeee", assistant="Le confirmo que su teléfono es 612 345 678"),
    )
    out = observe(calls_dir, write_map(tmp_path, {"55555555": str(scenario_path)}), tmp_path / "results")
    case = json.loads((out / "cases.jsonl").read_text().splitlines()[0])
    assert case["verdict"] == "fail"
    assert case["failure_signal"] == "transcript_leak"
    assert "privacy_error" in case["categories"]
    row = json.loads((out / "real_calls.jsonl").read_text().splitlines()[0])
    assert row["leaks"] == ["phone"]


def test_missing_leak_check_is_declared_not_silent(tmp_path: Path) -> None:
    calls_dir = tmp_path / "calls"
    write_call(calls_dir, "66666666-ffff", audit_lines("66666666-ffff"))
    out = observe(calls_dir, write_map(tmp_path, {"66666666": SCENARIO}), tmp_path / "results")
    case = json.loads((out / "cases.jsonl").read_text().splitlines()[0])
    assert "leak_check" in case["checks_not_run"]


def test_call_without_close_is_not_scored(tmp_path: Path) -> None:
    calls_dir = tmp_path / "calls"
    lines = [line for line in audit_lines("77777777-gggg") if '"call_ended"' not in line]
    write_call(calls_dir, "77777777-gggg", lines)
    out = observe(calls_dir, write_map(tmp_path, {"77777777": SCENARIO}), tmp_path / "results")
    case = json.loads((out / "cases.jsonl").read_text().splitlines()[0])
    assert case["verdict"] == "invalid_evaluation"


def test_oracle_map_prefix_and_ambiguity(tmp_path: Path) -> None:
    mapping = OracleMap(write_map(tmp_path, {"abc": SCENARIO}))
    assert mapping.scenario_for("abc-123")[1].id == "sb-001"
    assert mapping.scenario_for("zzz") is None
    ambiguous = write_map(tmp_path, {"abc": SCENARIO, "abcd": SCENARIO})
    with pytest.raises(ValueError, match="varias entradas"):
        OracleMap(ambiguous).scenario_for("abcdef")


def test_observe_writes_a_run_the_console_understands(tmp_path: Path) -> None:
    calls_dir = tmp_path / "calls"
    write_call(calls_dir, "88888888-hhhh", audit_lines("88888888-hhhh"))
    write_call(calls_dir, "99999999-iiii", audit_lines("99999999-iiii", book=None))
    out = observe(calls_dir, write_map(tmp_path, {"88888888": SCENARIO}), tmp_path / "results", run_id="obs-test")
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["experiment"] == "backend-observe"
    assert manifest["dataset_profile"]["counts"] == {"calls": 2, "tagged": 1, "untagged": 1}
    report = (out / "report.html").read_text(encoding="utf-8")
    assert "Llamadas reales observadas" in report
    assert "sin oráculo: informativa" in report

    # The generated run is readable by the read-only API like any other run.
    client = TestClient(create_app(tmp_path / "results", None))
    rows = client.get("/api/runs/obs-test/real-calls").json()
    assert {r["call_id"] for r in rows} == {"88888888-hhhh", "99999999-iiii"}
    detail = client.get("/api/runs/obs-test").json()
    assert detail["metrics"]["candidates"]["gemini_live"]["pass_rate"]["value"].startswith("100%")
    # A plain run without the observer file reports no real calls.
    assert client.get("/api/runs/obs-test/cases").status_code == 200


def test_scenario_paths_resolve_relative_to_the_map(tmp_path: Path) -> None:
    import shutil

    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    shutil.copy(SCENARIO, scenarios / "sb-001.yaml")
    calls_dir = tmp_path / "calls"
    write_call(calls_dir, "aaaa0000-jjjj", audit_lines("aaaa0000-jjjj"))
    out = observe(calls_dir, write_map(tmp_path, {"aaaa0000": "scenarios/sb-001.yaml"}), tmp_path / "results")
    case = json.loads((out / "cases.jsonl").read_text().splitlines()[0])
    assert case["scenario_id"] == "sb-001"
