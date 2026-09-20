"""Real-call statistics must preserve provenance and missing measurements."""
import json

from fastapi.testclient import TestClient

from evaluator.api.analytics import aggregate, call_metrics
from evaluator.api.app import create_app
from evaluator.api.history import HistoryStore
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
