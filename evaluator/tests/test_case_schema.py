"""One call schema for the whole lab, and old artifacts keep loading.

Contract tests for P0.3: a call declares its `schema_version`, its origin
(real / simulated / manual), the versions and links that produced it, its timing,
and the availability of each piece of evidence as `present` / `absent` /
`unknown` — never as a zero nobody measured. The transcript is an ordered list of
fragments with role and timestamp, and a source that only ever gave fragments is
never turned into invented turns.

The second half is the hard requirement: artifacts written by earlier runs load
with no migration. The legacy shapes are reconstructed here from the frozen
writers (`runner/experiment.py` and `observer/run.py`), because those two files
are outside P0's write surface: what this test pins is that their output keeps
working, not that it changes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evaluator.api.app import create_app
from evaluator.models import (
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    CaseResult,
    EvidenceAvailability,
    TranscriptEvent,
)
from evaluator.report.side_by_side import load_cases

RESULTS_ROOT = Path(__file__).resolve().parent.parent / "experiments" / "results"

# A v1 line exactly as `runner/experiment.py` writes it today: no schema_version,
# no origin, no evidence map, no transcript_events, no run link.
LEGACY_RUNNER_CASE: dict = {
    "case_id": "double-correct/sb-001/r0",
    "call_id": "692d11d18cf844caa9dbf88a332e799d",
    "scenario_id": "sb-001",
    "problem_id": "simple_booking",
    "candidate": "double-correct",
    "repetition": 0,
    "verdict": "pass",
    "failure_signal": None,
    "categories": [],
    "matched_outcome": 0,
    "field_diffs": [],
    "extra_actions": [],
    "missing_actions": [],
    "submitted": [{"action": "BOOK", "patient_id": "P00042"}],
    "submit_attempts": [{"route": "book", "status": 200}],
    "transcript": ["caller: Buenos días, quería una cita.", "agente: ¿Me dice su DNI?"],
    "turn_latencies_ms": [18.2],
    "first_audio_ms": 7.0,
    "cost": None,
    "usage": {},
    "audio": {
        "caller": "evidence/double-correct_sb-001_r0.caller.wav",
        "agent": "evidence/double-correct_sb-001_r0.agent.wav",
    },
    "interrupts": [],
    "checks_not_run": ["leak_check"],
    "notes": [],
    "duration_s": 0.96,
    "errors": [],
}

# A v1 line as `observer/run.py` writes it for a real observed call: the tagged
# path, with the note the observer always adds.
LEGACY_OBSERVER_CASE: dict = {
    "case_id": "backend-real/rules-001/obs-060b5378",
    "call_id": "060b5378aabbccddeeff001122334455",
    "scenario_id": "rules-001",
    "problem_id": "rules",
    "candidate": "backend-real",
    "repetition": 0,
    "verdict": "invalid_evaluation",
    "failure_signal": None,
    "categories": [],
    "matched_outcome": None,
    "field_diffs": [],
    "extra_actions": [],
    "missing_actions": [],
    "submitted": [],
    "submit_attempts": [],
    "transcript": ["caller: Hola, llamo por mi madre.", "agente: Clínica Arenal, buenos días."],
    "duration_s": 0.0,
    "notes": [
        "llamada real observada del audit del backend; sin audio ni latencias del cable",
        "el audit no registra el cierre de la llamada: el veredicto no es fiable",
    ],
    "checks_not_run": ["leak_check"],
}


def test_a_new_case_declares_its_version_origin_and_evidence():
    """A call written today says which schema, which origin and what evidence."""
    case = CaseResult(
        case_id="cand/sb-001/r0",
        call_id="c1",
        scenario_id="sb-001",
        problem_id="simple_booking",
        candidate="cand",
        repetition=0,
    )
    assert case.schema_version == SCHEMA_VERSION
    assert json.loads(case.model_dump_json())["schema_version"] == SCHEMA_VERSION
    assert case.origin == "simulated"
    assert case.evidence.as_dict() == {
        "audio": "unknown",
        "transcript": "unknown",
        "cost": "unknown",
        "outcome": "present",
    }
    assert set(case.evidence.as_dict()) == {"audio", "transcript", "cost", "outcome"}


def _read_from_disk(payload: dict) -> CaseResult:
    """Exactly how `load_cases` reads a line: JSON text, not a dict."""
    return CaseResult.model_validate_json(json.dumps(payload))


class TestLegacyArtifacts:
    """An artifact from an earlier run loads with no manual migration."""

    def test_a_legacy_runner_case_loads_and_is_read_as_simulated(self):
        case = _read_from_disk(LEGACY_RUNNER_CASE)
        assert case.schema_version == LEGACY_SCHEMA_VERSION
        assert case.origin == "simulated"
        assert case.candidate == "double-correct"
        assert case.verdict == "pass"
        assert case.evidence.audio == "present"
        assert case.evidence.transcript == "present"
        assert case.evidence.cost == "unknown", "coste ausente no es coste cero"
        assert case.evidence.outcome == "present"

    def test_a_legacy_observer_case_loads_and_is_read_as_a_real_call(self):
        case = _read_from_disk(LEGACY_OBSERVER_CASE)
        assert case.schema_version == LEGACY_SCHEMA_VERSION
        assert case.origin == "real"
        assert case.evidence.audio == "unknown", "nadie miró si había audio: no es un cero"
        assert case.evidence.outcome == "absent", "no evaluable no es un veredicto"

    def test_legacy_transcript_lines_become_ordered_fragments_not_turns(self):
        case = _read_from_disk(LEGACY_RUNNER_CASE)
        events = case.ordered_transcript
        assert [event.text for event in events] == [
            "Buenos días, quería una cita.",
            "¿Me dice su DNI?",
        ]
        assert [event.role for event in events] == ["caller", "agent"]
        assert all(event.fragment for event in events), "cada línea es un fragmento, no un turno"
        assert all(event.timestamp is None for event in events)
        assert all(event.source == "legacy_transcript" for event in events)

    def test_the_legacy_per_speaker_field_keeps_working(self):
        case = _read_from_disk(LEGACY_RUNNER_CASE)
        assert case.transcript == LEGACY_RUNNER_CASE["transcript"]

    def test_the_version_comes_from_the_file_not_from_this_process(self):
        # The same payload read as text and built as a dict differ on purpose:
        # only the file knows whether it ever declared a version.
        assert _read_from_disk(LEGACY_RUNNER_CASE).schema_version == LEGACY_SCHEMA_VERSION
        assert (
            CaseResult.model_validate(LEGACY_RUNNER_CASE).schema_version == SCHEMA_VERSION
        )

    def test_a_string_version_is_read_as_a_number(self):
        case = _read_from_disk({**LEGACY_RUNNER_CASE, "schema_version": "2"})
        assert case.schema_version == 2

    def test_a_future_version_and_unknown_fields_do_not_break_reading(self):
        case = _read_from_disk(
            {
                **LEGACY_RUNNER_CASE,
                "schema_version": 99,
                "evidence": {"audio": "present"},
                "something_new": {"a": 1},
            }
        )
        assert case.schema_version == 99
        assert case.evidence.transcript == "unknown"
        assert not hasattr(case, "something_new")

    def test_a_complete_new_artifact_keeps_what_it_declares(self):
        case = _read_from_disk(
            {
                **LEGACY_RUNNER_CASE,
                "schema_version": SCHEMA_VERSION,
                "origin": "manual",
                "run_id": "run-1",
                "candidate_version": "lab-1",
                "evidence": EvidenceAvailability(
                    audio="present", transcript="absent", cost="unknown", outcome="present"
                ).model_dump(),
                "transcript_events": [
                    TranscriptEvent(
                        role="caller",
                        text="hola",
                        timestamp="2026-09-19T10:00:00+00:00",
                        offset_s=0.5,
                        fragment=True,
                        source="agent_audit",
                    ).model_dump()
                ],
            }
        )
        assert case.origin == "manual"
        assert case.run_id == "run-1"
        assert case.candidate_version == "lab-1"
        assert case.evidence.transcript == "absent"
        assert case.evidence.as_dict()["audio"] == "present"
        assert case.transcript_events[0].role == "caller"
        assert case.transcript_events[0].offset_s == 0.5
        assert case.transcript_events[0].fragment is True


@pytest.mark.skipif(
    not any(RESULTS_ROOT.glob("*/cases.jsonl")),
    reason="no hay corridas locales bajo experiments/results",
)
class TestRunsAlreadyOnDisk:
    """The runs that already exist keep loading, and keep answering over HTTP.

    This is the literal acceptance criterion of P0.3: not a fixture, the runs
    this repository has already produced. It skips (with a reason) on a clean
    checkout, where the directory is Git-ignored and legitimately empty.
    """

    def test_every_case_on_disk_loads_with_a_version_and_an_origin(self):
        seen = 0
        for run in sorted(RESULTS_ROOT.glob("*/cases.jsonl")):
            for case in load_cases(run.parent):
                seen += 1
                assert case.schema_version >= LEGACY_SCHEMA_VERSION
                assert case.origin in {"real", "simulated", "manual", "unknown"}
                assert set(case.evidence.as_dict()) == {
                    "audio",
                    "transcript",
                    "cost",
                    "outcome",
                }
        assert seen > 0

    def test_the_run_endpoints_still_answer_for_existing_runs(self):
        client = TestClient(create_app(RESULTS_ROOT))
        rows = client.get("/api/runs").json()
        assert rows, "las corridas locales tienen que seguir listándose"
        for row in rows:
            detail = client.get(f"/api/runs/{row['run_id']}")
            assert detail.status_code == 200, detail.text
            cases = client.get(f"/api/runs/{row['run_id']}/cases")
            assert cases.status_code == 200, cases.text
            for case in cases.json():
                assert case["run_id"] == row["run_id"]

    def test_a_case_links_back_to_the_run_and_the_candidate_version(self, tmp_path):
        run = tmp_path / "20260919T170000Z-abc123"
        run.mkdir()
        (run / "cases.jsonl").write_text(
            json.dumps(LEGACY_RUNNER_CASE) + "\n", encoding="utf-8"
        )
        (run / "manifest.json").write_text(
            json.dumps({"candidates": [{"name": "double-correct", "version": "lab-7"}]}),
            encoding="utf-8",
        )
        client = TestClient(create_app(tmp_path))
        case = client.get("/api/runs/20260919T170000Z-abc123/cases").json()[0]
        assert case["run_id"] == "20260919T170000Z-abc123"
        assert case["candidate_version"] == "lab-7"
        assert case["schema_version"] == LEGACY_SCHEMA_VERSION
        assert case["evidence"]["cost"] == "unknown"
