"""The API answers from files a run already wrote, and never invents data.

These tests build a synthetic results directory - one run, two candidates, a
couple of cases, a report and one WAV - and check the JSON the console will
read, including the answers it must refuse: unknown runs, path traversal, and
evidence that is not inside the run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evaluator.api.app import create_app
from evaluator.models import CaseResult

RUN = "20260919T170000Z-abc123"


def _case(candidate: str, scenario_id: str, verdict: str, **kwargs) -> CaseResult:
    return CaseResult(
        case_id=kwargs.pop("case_id", f"{candidate}/{scenario_id}/r0"),
        call_id=f"call-{candidate}-{scenario_id}",
        scenario_id=scenario_id,
        problem_id=kwargs.pop("problem_id", "simple_booking"),
        candidate=candidate,
        repetition=kwargs.pop("repetition", 0),
        verdict=verdict,
        **kwargs,
    )


@pytest.fixture
def results_root(tmp_path) -> Path:
    run = tmp_path / RUN
    run.mkdir()
    audio = run / "evidence"
    audio.mkdir()
    agent_wav = audio / "agent.wav"
    agent_wav.write_bytes(b"RIFFfake")
    cases = [
        _case(
            "baseline",
            "sb-001",
            "pass",
            turn_latencies_ms=[100, 200],
            first_audio_ms=900,
            submitted=[{"action": "BOOK"}],
            submit_attempts=[{"status": 200}],
            cost=0.25,
            duration_s=42,
            audio={"agent": str(agent_wav)},
        ),
        _case("candidate", "sb-001", "fail", failure_signal="record_mismatch", repetition=0),
        _case(
            "candidate",
            "ns-001",
            "invalid_evaluation",
            problem_id="nearest_site",
            errors=["candidate never answered: boom"],
            case_id="candidate/ns-001/r0",
        ),
    ]
    (run / "cases.jsonl").write_text(
        "".join(case.model_dump_json() + "\n" for case in cases), encoding="utf-8"
    )
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": RUN,
                "experiment": "evaluator-smoke",
                "started_at": "2026-09-19T17:00:00+00:00",
                "repetitions": 1,
                "candidates": [{"name": "baseline"}, {"name": "candidate"}],
            }
        ),
        encoding="utf-8",
    )
    (run / "report.html").write_text("<html>report</html>", encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(results_root) -> TestClient:
    return TestClient(create_app(results_root))


class TestRuns:
    def test_health_names_the_root(self, client, results_root):
        body = client.get("/healthz").json()
        assert body["status"] == "ok"
        assert body["runs"] == 1

    def test_run_list_carries_the_counts_a_person_scans(self, client):
        rows = client.get("/api/runs").json()
        assert rows[0]["run_id"] == RUN
        assert rows[0]["experiment"] == "evaluator-smoke"
        assert rows[0]["cases"] == 3
        assert rows[0]["passed"] == 1
        assert rows[0]["failed"] == 1
        assert rows[0]["invalid"] == 1
        assert rows[0]["has_report"] is True

    def test_detail_pairs_metrics_with_the_side_by_side(self, client):
        body = client.get(f"/api/runs/{RUN}").json()
        assert body["run_id"] == RUN
        assert body["metrics"]["candidates"]["baseline"]["pass_rate"]["value"] == "100% (1/1)"
        assert body["metrics"]["candidates"]["candidate"]["invalid"]["value"] == "1"
        assert body["side_by_side"]["candidates"] == ["baseline", "candidate"]

    def test_cases_are_returned_whole(self, client):
        cases = client.get(f"/api/runs/{RUN}/cases").json()
        assert len(cases) == 3
        assert {case["candidate"] for case in cases} == {"baseline", "candidate"}

    def test_compare_marks_the_disagreement(self, client):
        body = client.get(f"/api/runs/{RUN}/compare").json()
        # sb-001 has both candidates and they disagree; ns-001 only ran one.
        assert body["summary"]["disagreements"] == 1
        row = next(r for r in body["rows"] if r["scenario_id"] == "sb-001")
        assert row["disagrees"] is True
        assert row["cells"]["baseline"] == "PASA 150ms"
        assert row["cells"]["candidate"] == "FALLA:record_mismatch"

    def test_report_is_served_as_html(self, client):
        response = client.get(f"/api/runs/{RUN}/report")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "report" in response.text

    def test_evidence_wav_is_served(self, client):
        response = client.get(
            f"/api/runs/{RUN}/evidence/agent", params={"case_id": "baseline/sb-001/r0"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"

    def test_evidence_for_a_missing_stream_is_explained(self, client):
        response = client.get(
            f"/api/runs/{RUN}/evidence/caller", params={"case_id": "baseline/sb-001/r0"}
        )
        assert response.status_code == 404
        assert "caller" in response.json()["detail"]

    def test_errors_reach_the_console(self, client):
        body = client.get(f"/api/runs/{RUN}").json()
        assert body["metrics"]["errors"] == ["candidate never answered: boom"]


class TestRefusals:
    def test_unknown_run_is_404(self, client):
        assert client.get("/api/runs/nope").status_code == 404

    @pytest.mark.parametrize("run_id", ["a/b", "a\\b"])
    def test_a_run_id_is_never_a_path(self, client, run_id):
        assert client.get(f"/api/runs/{run_id}").status_code in (400, 404)

    def test_dot_names_are_refused_before_the_url_router_normalises_them(self, results_root):
        # A browser (and Starlette) collapses `/api/runs/.` before routing, so the
        # guard is checked where it lives rather than through the wire.
        from fastapi import HTTPException

        from evaluator.api.app import _run_dir

        for name in (".", "..", "", "a/b"):
            with pytest.raises(HTTPException) as error:
                _run_dir(results_root, name)
            assert error.value.status_code in (400, 404)

    def test_traversal_out_of_the_results_root_is_refused(self, client):
        assert client.get("/api/runs/..%2F..%2Fetc").status_code in (400, 404)

    def test_a_run_without_cases_is_not_a_run(self, client, results_root):
        (results_root / "empty-dir").mkdir()
        assert client.get("/api/runs/empty-dir").status_code == 404

    def test_unknown_case_evidence_is_404(self, client):
        response = client.get(
            f"/api/runs/{RUN}/evidence/agent", params={"case_id": "nope"}
        )
        assert response.status_code == 404


class TestEmptyRoot:
    def test_no_runs_is_an_empty_list_not_an_error(self, tmp_path):
        client = TestClient(create_app(tmp_path))
        assert client.get("/api/runs").json() == []
        assert client.get("/healthz").json()["runs"] == 0
