"""Real-call statistics must preserve provenance and missing measurements."""
import json

from fastapi.testclient import TestClient

from evaluator.api.analytics import aggregate, call_incidents, call_metrics
from evaluator.api.app import create_app
from evaluator.api.history import HistoryStore
from evaluator.api.production import ProductionSource
from evaluator.observer.backend_calls import load_backend_calls
from evaluator.observer.run import observe


def audit(tmp_path):
    root = tmp_path / "data"
    directory = root / "arenal" / "calls"
    directory.mkdir(parents=True)
    events = [
        ("call_context_created", {"org_id": "arenal"}),
        ("engine_selected", {"engine": "cascade", "model": "test-model", "version": "abc123"}),
        ("pipeline_stage", {"stage": "client_connected"}),
        ("pipeline_stage", {"stage": "assistant_audio_emitted"}),
        ("transcript", {"role": "caller", "text": "Hola"}),
        ("transcript", {"role": "assistant", "text": "Buenos días"}),
        ("transcript", {"role": "caller", "text": "Necesito información"}),
        ("call_ended", {"elapsed_s": 7}),
    ]
    (directory / "call-test.jsonl").write_text("\n".join(
        json.dumps({"ts": f"2026-09-20T10:00:{i:02}Z", "event": event, "data": data})
        for i, (event, data) in enumerate(events)
    ) + '\n{"partial":', encoding="utf-8")
    return root


def test_org_layout_and_original_transcript_order(tmp_path):
    calls = load_backend_calls(audit(tmp_path))
    assert len(calls) == 1
    call = calls[0]
    assert call.model == "test-model" and call.version == "abc123"
    assert [e["role"] for e in call.transcript_events] == ["caller", "agent", "caller"]
    assert call.transcript_events[1]["timestamp"] == "2026-09-20T10:00:05Z"


def test_missing_audio_latency_not_fabricated_from_transcript(tmp_path):
    store = HistoryStore(tmp_path / "results")
    store.import_backend_audits(audit(tmp_path))
    row = store.calls({"origin": "real"})[0]
    metrics = call_metrics(row)
    assert metrics["response_ms"] == []
    assert metrics["transcript_gap_ms"] == [1000]
    assert metrics["first_audio_ms"] == 1000
    totals = aggregate([row])
    assert totals["response_p50_ms"] is None
    assert totals["pass_rate"] is None
    assert totals["quality"] is None
    assert totals["recovered"] is None


def test_recovery_requires_correlated_audio_evidence():
    row = {"timeline": [
        {"event": "barge_in_reset", "data": {"interruption_id": "a"}},
        {"event": "barge_in_reset", "data": {"interruption_id": "a"}},
        {"event": "barge_in_reset", "data": {"interruption_id": "b"}},
        {"event": "barge_in_reset", "data": {"interruption_id": "c"}},
        {"event": "interruption_recovered", "data": {"interruption_id": "a"}},
        {"event": "interruption_recovered", "data": {"interruption_id": "other"}},
        {"event": "interruption_unrecovered", "data": {"interruption_id": "b"}},
    ]}
    metrics = call_metrics(row)
    assert metrics["interruptions"] == 3
    assert metrics["recovered"] == 1
    assert metrics["recovery_observed"] == 2


def test_incidents_distinguish_failures_from_telemetry_gaps():
    broken = {"ended": True, "transcript_events": [{"role": "caller", "text": "hola"}],
              "timeline": [{"event": "barge_in_reset", "data": {"resets": 3}}],
              "errors": ["submission refused"]}
    incidents = call_incidents(broken)
    assert {item["code"] for item in incidents} >= {"agent_silent", "submission_failed", "recovery_unknown"}
    assert next(item for item in incidents if item["code"] == "recovery_unknown")["severity"] == "telemetry"


def test_manual_and_backend_evidence_are_one_call(tmp_path):
    root = audit(tmp_path)
    results = tmp_path / "results"
    directory = results / "_manual-calls"
    directory.mkdir(parents=True)
    (directory / "call-test.json").write_text(json.dumps({
        "call_id": "call-test", "profile_id": "wrong-label", "audio_files": {"caller": "caller.wav"},
        "evidence": {"audio": "present"}, "submit_attempts": [{"status": 200}]}))
    store = HistoryStore(results)
    store.import_runs()
    store.import_backend_audits(root)
    rows = store.calls({"source": "tests"})
    assert len(rows) == 1
    assert rows[0]["origin"] == "manual"
    assert rows[0]["candidate"] == "cascade"
    assert rows[0]["audio_files"]["caller"] == "caller.wav"
    assert rows[0]["transcript_events"]
    assert rows[0]["submit_attempts"] == [{"status": 200}]
    assert store.call(rows[0]["id"]) == rows[0]


def test_transport_error_is_not_submission_failure():
    incidents = call_incidents({"ended": True, "errors": ["websocket connection closed"],
        "transcript_events": [{"role": "agent", "text": "Hola"}]})
    assert "submission_failed" not in {item["code"] for item in incidents}
    assert "transport_error" in {item["code"] for item in incidents}
    assert next(item for item in incidents if item["code"] == "caller_silent")["severity"] == "telemetry"


def test_observer_snapshots_do_not_multiply_real_calls(tmp_path):
    root = audit(tmp_path)
    results = tmp_path / "results"
    observe(root, None, results, "snapshot-a")
    observe(root, None, results, "snapshot-b")
    store = HistoryStore(results)
    store.import_runs()
    store.import_backend_audits(root)
    assert len(store.calls({"origin": "real"})) == 1


def test_api_real_history_model_and_filters(tmp_path):
    with TestClient(create_app(tmp_path / "results", audit_root=audit(tmp_path))) as client:
        response = client.get("/api/analytics").json()
        assert response["summary"]["calls"] == 1
        assert response["models"][0]["model"] == "test-model"
        assert response["models"][0]["version"] == "abc123"
        assert client.get("/api/analytics?from=2027-01-01").json()["summary"]["calls"] == 0
        assert client.get("/api/analytics?candidate=unknown").json()["models"] == []


def test_nan_and_negative_values_not_measurements():
    result = aggregate([{"turn_latencies_ms": [None, -5, float("nan"), 0, 1000]}])
    assert result["response_n"] == 2
    assert result["response_p50_ms"] == 500


def test_production_calls_sync_on_analytics_refresh(tmp_path, monkeypatch):
    exported = [{"call_id": "prod-1", "records": [
        {"ts": "2026-09-20T10:00:00Z", "event": "engine_selected", "data": {"engine": "gemini_live", "model": "live-model"}},
        {"ts": "2026-09-20T10:00:01Z", "event": "transcript", "data": {"role": "caller", "text": "hola"}},
        {"ts": "2026-09-20T10:00:03Z", "event": "call_ended", "data": {"elapsed_s": 3}},
    ]}]
    monkeypatch.setattr(ProductionSource, "fetch", lambda self: exported)
    with TestClient(create_app(tmp_path / "results", production_token="token")) as client:
        analytics = client.get("/api/analytics").json()
        assert analytics["summary"]["calls"] == 1
        assert analytics["source"]["production"]["available"] is True
        rows = client.get("/api/history/calls", params={"origin": "real"}).json()
        assert rows["items"][0]["call_id"] == "prod-1"
        assert rows["items"][0]["source"] == "production"
