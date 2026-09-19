"""Contract tests for the persistent history and server-owned job API."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from evaluator.api.app import create_app
from evaluator.models import CaseResult
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


def test_jobs_refuse_client_destinations_and_unknown_scenarios(tmp_path: Path):
    root = _results(tmp_path)
    client = TestClient(create_app(root, profiles=_profile(), scenario_root=tmp_path))
    rejected = client.post("/api/jobs", json={
        "profile_ids": ["local-double"], "scenario_ids": ["nope"], "mode": "text", "ws_url": "secret"
    })
    assert rejected.status_code == 400
    assert "ws_url" in rejected.json()["detail"]
    assert "secret" not in rejected.text


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
