"""Contract tests for the persistent history and server-owned job API."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evaluator.api.app import create_app
from evaluator.api.jobs import JobStore
from evaluator.models import CaseResult, ExperimentConfig
from evaluator.profiles import AgentProfile, ProfileCatalog


def _profile() -> ProfileCatalog:
    profile = AgentProfile.from_declaration(
        {
            "id": "local-double",
            "engine": "double",
            "version": "test-1",
            "endpoints": {"text_url": "http://127.0.0.1:18770"},
            "capabilities": {"text": True, "transcript": True},
            "providers": {"name": "doble local"},
        }
    )
    return ProfileCatalog([profile])


def _results(tmp_path: Path) -> Path:
    run = tmp_path / "run-1"
    run.mkdir()
    case = CaseResult(
        case_id="local-double/demo/r0", call_id="sim-1", scenario_id="demo",
        problem_id="simple_booking", candidate="local-double", candidate_version="test-1",
        repetition=0, verdict="pass", transcript=["caller: hola"], cost=None,
    )
    (run / "cases.jsonl").write_text(case.model_dump_json() + "\n", encoding="utf-8")
    (run / "manifest.json").write_text(
        '{"started_at":"2026-09-20T10:00:00+00:00","candidates":[{"name":"local-double","kind":"double","version":"test-1"}]}',
        encoding="utf-8",
    )
    return tmp_path


def test_history_import_is_idempotent_and_doubles_are_opt_in(tmp_path: Path):
    root = _results(tmp_path)
    client = TestClient(create_app(root, profiles=_profile(), scenario_root=tmp_path))
    first = client.post("/api/history/import", json={"source": "runs"}).json()
    second = client.post("/api/history/import", json={"source": "runs"}).json()
    assert first["created"] == 1
    assert second["created"] == 0
    assert client.get("/api/history/calls").json()["total"] == 0
    rows = client.get("/api/history/calls", params={"include_doubles": "true"}).json()
    assert rows["total"] == 1
    detail = client.get(f"/api/history/calls/{rows['items'][0]['id']}").json()
    assert detail["evidence"]["cost"] == "unknown"
    assert detail["transcript_events"][0]["fragment"] is True


def test_unchanged_runs_are_not_reparsed_or_rewritten(tmp_path, monkeypatch):
    from evaluator.api import history

    _results(tmp_path)
    store = history.HistoryStore(tmp_path)
    store.import_runs()
    stamp = store.path.stat().st_mtime_ns
    monkeypatch.setattr(history, "_cases", lambda _: pytest.fail("unchanged artifact reparsed"))
    result = store.import_runs()
    assert result["updated"] == 0
    assert store.path.stat().st_mtime_ns == stamp


def test_jobs_refuse_client_destinations_and_unknown_scenarios(tmp_path: Path):
    root = _results(tmp_path)
    client = TestClient(create_app(root, profiles=_profile(), scenario_root=tmp_path))
    rejected = client.post("/api/jobs", json={
        "profile_ids": ["local-double"], "scenario_ids": ["nope"], "mode": "text", "ws_url": "secret"
    })
    assert rejected.status_code == 400
    assert "ws_url" in rejected.json()["detail"]
    assert "secret" not in rejected.text


def test_job_publishes_progress_and_rejects_overlapping_runs(tmp_path, monkeypatch):
    import json
    import threading
    import time

    from evaluator.api import jobs

    entered, finish = threading.Event(), threading.Event()
    catalog = _profile()
    store = JobStore(tmp_path, catalog, tmp_path)
    monkeypatch.setattr(store, "_scenario_path", lambda _: tmp_path / "scenario.yaml")
    monkeypatch.setattr(jobs, "verify_clinic", lambda *args: None)

    def run(config, root, cancel_requested, on_progress):
        out = Path(root) / "run-progress"
        out.mkdir()
        on_progress(out, 1, 2)
        entered.set()
        assert finish.wait(5)
        (out / "manifest.json").write_text(json.dumps({"completed_cases": 1, "status": "cancelled" if cancel_requested() else "completed"}))
        return out

    monkeypatch.setattr(jobs, "run_experiment", run)
    body = {"profile_ids": ["local-double"], "scenario_ids": ["test"], "mode": "text"}
    job = store.create(body)
    try:
        assert entered.wait(5)
        assert store.get(job["id"])["progress"]["completed"] == 1
        assert store.get(job["id"])["run_id"] == "run-progress"
        with pytest.raises(jobs.JobError, match="activo"):
            store.create(body)
        store.cancel(job["id"])
    finally:
        finish.set()
    deadline = time.monotonic() + 5
    while store.get(job["id"])["status"] not in jobs.TERMINAL and time.monotonic() < deadline:
        time.sleep(.01)
    assert store.get(job["id"])["status"] == "cancelled"


def test_job_configuration_preserves_voice_and_profile_binding(tmp_path, monkeypatch):
    catalog = ProfileCatalog.builtin()
    profile = catalog.get("cascade").model_copy(update={"start_command": "local-agent"})
    store = JobStore(tmp_path, catalog, tmp_path)
    monkeypatch.setattr(store, "get", lambda _: {"mode": "voice", "repetitions": 2})
    config = ExperimentConfig.load(str(store._write_config("job-test", [profile], [])))
    assert config.tts_command == profile.laboratory.tts
    assert config.clinic_mode == "existing"
    assert config.clinic_url == profile.laboratory.clinic_url
    assert config.candidates[0].start_command == "local-agent"
    assert config.candidates[0].env["VOICE_ENGINE"] == "cascade"
    assert config.candidates[0].text_url is None


def test_live_audit_root_is_read_directly_without_an_observer_run(tmp_path: Path):
    audit = tmp_path / "calls"
    audit.mkdir()
    (audit / "call-1.jsonl").write_text(
        '{"ts":"2026-09-20T10:00:00Z","event":"engine_selected","data":{"engine":"cascade"}}\n'
        '{"ts":"2026-09-20T10:00:01Z","event":"transcript","data":{"role":"caller","text":"hola"}}\n'
        '{"ts":"2026-09-20T10:00:02Z","event":"call_ended","data":{"elapsed_s":2}}\n',
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path / "results", audit_root=audit))
    response = client.get("/api/history/calls", params={"include_doubles": "true"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert not (tmp_path / "results" / "live-backend").exists()
