"""Full-experiment integration: the artifacts a run must leave behind.

Runs a tiny real experiment (two doubles, one scenario, free ports) and checks
the things a developer reads afterwards: `metrics.json` next to `cases.jsonl`,
audio volume measured from the wire, and the report carrying the new columns.
Ports are far from the ones other people run (18090 / 18770-2 / 7860).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from evaluator.runner.experiment import run_experiment

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"

# 0.4 s of µ-law silence: one byte per 8 kHz sample.
CALLER_ULAW = bytes([0xFF]) * 3200

BOOK = {
    "action": "BOOK",
    "patient_id": "P00042",
    "provider_id": "PR01",
    "location_id": "centro",
    "appointment_type_id": "review",
    "slot": "2026-09-21T09:00:00+02:00",
    "policy_id": "sanitas",
}


def _write_experiment(tmp_path: Path) -> Path:
    scenario_dir = tmp_path / "scenarios"
    scenario_dir.mkdir()
    (scenario_dir / "caller.ulaw").write_bytes(CALLER_ULAW)
    (scenario_dir / "mini-001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "mini-001",
                "problem_id": "simple_booking",
                "clock": "2026-09-18T10:00:00+02:00",
                "clinic_fixture": "seed-v1",
                "caller": {"from_number": "+34612345678", "facts": {"patient_id": "P00042"}},
                "turns": [{"text": "Hola", "audio": "caller.ulaw", "hold_ms": 300}],
                "oracle": {"accepted_outcomes": [{"actions": [BOOK]}]},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    config = {
        "name": "metrics-integration",
        "clinic_dataset": str(DATASET),
        "clinic_port": 18992,
        "submit_drain_s": 0.5,
        "candidates": [
            {"name": "double-correct", "kind": "double", "port": 18993, "mode": "correct"},
            {"name": "double-wrong", "kind": "double", "port": 18994, "mode": "mutate"},
        ],
        "scenarios": ["scenarios/mini-001.yaml"],
    }
    path = tmp_path / "mini.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


def test_partial_results_survive_failure_with_progress(tmp_path, monkeypatch):
    from evaluator.models import CaseResult
    from evaluator.runner import experiment

    config = _write_experiment(tmp_path)
    progress = []

    async def run_case(*args, **kwargs):
        if any(completed for _, completed, _ in progress):
            raise RuntimeError("synthetic failure")
        return CaseResult(case_id="one", call_id="one", scenario_id="mini-001", problem_id="simple_booking", candidate="double-correct", repetition=0)

    monkeypatch.setattr(experiment, "_run_case", run_case)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        run_experiment(str(config), str(tmp_path / "results"),
            on_progress=lambda path, completed, total: progress.append((path, completed, total)))
    out = progress[0][0]
    assert [item[1] for item in progress] == [0, 1]
    assert len((out / "cases.jsonl").read_text().splitlines()) == 1
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["completed_cases"] == 1
    assert manifest["started_at"] <= manifest["ended_at"]
    assert manifest["scenarios"][0]["sha256"]
    assert manifest["config_hash"]


def test_a_run_writes_metrics_and_measures_audio(tmp_path: Path) -> None:
    config = _write_experiment(tmp_path)
    out = run_experiment(str(config), str(tmp_path / "results"))

    cases = [
        json.loads(line)
        for line in (out / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(cases) == 2
    correct = next(c for c in cases if c["candidate"] == "double-correct")
    assert correct["verdict"] == "pass"
    # Wire counters and volume: measured, not inferred from the WAV afterwards.
    assert correct["frames_sent"] and correct["frames_sent"] > 0
    assert correct["caller_audio_s"] and correct["caller_audio_s"] > 0
    assert correct["agent_audio_s"] and correct["agent_audio_s"] > 0

    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    per_candidate = metrics["candidates"]["double-correct"]
    assert per_candidate["audio_caller_s"]["value"].endswith("s")
    assert per_candidate["audio_caller_s"]["denominator"] == 1
    assert per_candidate["audio_ratio"]["value"] != "n/d"
    assert per_candidate["pass_rate"]["value"] == "100% (1/1)"
    assert per_candidate["errors_by_type"]["value"] == "n/d"
    assert metrics["candidates"]["double-wrong"]["pass_rate"]["value"] == "0% (0/1)"

    report = (out / "report.html").read_text(encoding="utf-8")
    assert "audio caller/agente" in report
    assert "casos con errores" in report
    assert "turnos (mediana)" in report
