"""Error contracts of the evidence routes the console depends on.

The judge and the audio player are the two places where the laboratory reads
historical evidence back. A wrong status hides a real limitation behind a broken
screen, and an unchecked path lets a request read a file outside the results
root. Both are asserted here.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from evaluator.api.app import create_app
from evaluator.api.judge import KEY_ENV_VARS

WAV = b"RIFF$\x00\x00\x00WAVEfmt "


def clear_judge_key(monkeypatch):
    for name in KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def audit_file(root: Path, name: str, events: list[tuple[str, dict]]) -> Path:
    directory = root / "arenal" / "calls"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        "\n".join(
            json.dumps({"ts": f"2026-09-20T10:00:{i:02}Z", "event": event, "data": data})
            for i, (event, data) in enumerate(events)
        ) + "\n",
        encoding="utf-8",
    )
    return root


CONVERSATION = [
    ("engine_selected", {"engine": "cascade", "model": "m1", "version": "v1"}),
    ("transcript", {"role": "caller", "text": "Buenos días, quiero una cita"}),
    ("transcript", {"role": "assistant", "text": "Claro, ¿qué día le viene bien?"}),
]
CLOSED = [*CONVERSATION, ("call_ended", {"elapsed_s": 12, "reason": "caller_hangup"})]


def manual_archive(root: Path, call_id: str, **extra) -> None:
    directory = root / "_manual-calls"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "call_id": call_id, "profile_id": "test-voice", "started_at": "2026-09-20T09:00:00Z",
        "ended_at": "2026-09-20T09:01:00Z", "duration_s": 60.0,
        "turns": [{"role": "caller", "text": "Hola"}],
        "audio_files": extra.pop("audio_files", {}),
        "transport_error": extra.pop("transport_error", None), "evidence": {},
        **extra,
    }
    (directory / f"{call_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def manual_row(client: TestClient, call_id: str) -> dict:
    client.post("/api/history/import")
    rows = client.get("/api/history/calls?origin=manual").json()["items"]
    return next(row for row in rows if row["call_id"] == call_id)


def test_judge_route_rejects_unknown_open_and_empty_calls(tmp_path, monkeypatch):
    clear_judge_key(monkeypatch)
    results = tmp_path / "results"
    audit = audit_file(tmp_path / "data", "open.jsonl", CONVERSATION)
    with TestClient(create_app(results, audit_root=audit)) as client:
        assert client.post("/api/history/calls/does-not-exist/judge").status_code == 404
        open_call = client.get("/api/history/calls?origin=real").json()["items"][0]
        denied = client.post(f"/api/history/calls/{open_call['id']}/judge")
        assert denied.status_code == 422
        assert "abierta" in denied.json()["detail"]


def test_judge_route_needs_a_key_and_refuses_empty_transcripts(tmp_path, monkeypatch):
    clear_judge_key(monkeypatch)
    results = tmp_path / "results"
    audit = audit_file(tmp_path / "data", "closed.jsonl", CLOSED)
    with TestClient(create_app(results, audit_root=audit)) as client:
        row = client.get("/api/history/calls?origin=real").json()["items"][0]
        no_key = client.post(f"/api/history/calls/{row['id']}/judge")
        assert no_key.status_code == 422
        assert "EVALUATOR_JUDGE_API_KEY" in no_key.json()["detail"]

    silent = audit_file(tmp_path / "silent", "no-text.jsonl", [*CLOSED[:1], CLOSED[-1]])
    with TestClient(create_app(results, audit_root=silent)) as client:
        empty = client.get("/api/history/calls?origin=real").json()["items"][0]
        response = client.post(f"/api/history/calls/{empty['id']}/judge")
        assert response.status_code == 422
        assert "transcripción" in response.json()["detail"]


def test_judge_route_stores_an_evidence_bound_review(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALUATOR_JUDGE_API_KEY", "test-key")
    calls = []

    async def post(self, url, **kwargs):
        calls.append(kwargs)
        review = {"outcome": "pass", "quality": 4, "reason": "Gestiona la cita",
                  "evidence_indices": [0, 1], "limitations": ["Sin agenda real"]}
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": json.dumps(review)}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    results = tmp_path / "results"
    audit = audit_file(tmp_path / "data", "closed.jsonl", CLOSED)
    with TestClient(create_app(results, audit_root=audit)) as client:
        row = client.get("/api/history/calls?origin=real").json()["items"][0]
        review = client.post(f"/api/history/calls/{row['id']}/judge")
        assert review.status_code == 200
        body = review.json()
        assert body["outcome"] == "pass" and body["source"] == "llm_judge"
        assert body["evidence_hash"] and body["model"]
        # The cached review is returned without a second provider call.
        assert client.get(f"/api/history/calls/{row['id']}").json()["judgment"]["outcome"] == "pass"
    assert len(calls) == 1
    assert "test-key" not in json.dumps(body)


def test_audio_route_serves_only_inside_the_results_root(tmp_path):
    results = tmp_path / "results"
    manual_archive(results, "mic-real", audio_files={"caller": "_live-audio/mic-real/caller.wav"})
    manual_archive(results, "mic-empty", audio_files={})
    manual_archive(results, "mic-escape", audio_files={"caller": "../outside.wav"})
    (results / "_live-audio" / "mic-real").mkdir(parents=True)
    (results / "_live-audio" / "mic-real" / "caller.wav").write_bytes(WAV)
    (tmp_path / "outside.wav").write_bytes(WAV)

    with TestClient(create_app(results)) as client:
        assert client.get("/api/history/calls/nope/audio/caller").status_code == 404

        real = manual_row(client, "mic-real")
        served = client.get(f"/api/history/calls/{real['id']}/audio/caller")
        assert served.status_code == 200
        assert served.content == WAV
        assert served.headers["content-type"] == "audio/wav"
        assert client.get(f"/api/history/calls/{real['id']}/audio/agent").status_code == 404

        empty = manual_row(client, "mic-empty")
        unavailable = client.get(f"/api/history/calls/{empty['id']}/audio/caller")
        assert unavailable.status_code == 404
        assert "grabación" in unavailable.json()["detail"]

        escape = manual_row(client, "mic-escape")
        # The target exists and is a real WAV: only the containment guard can refuse it.
        assert (tmp_path / "outside.wav").is_file()
        assert client.get(f"/api/history/calls/{escape['id']}/audio/caller").status_code == 404


@pytest.mark.parametrize("stream", ["", "../caller", "caller/../../x"])
def test_audio_route_rejects_unknown_stream_names(tmp_path, stream):
    results = tmp_path / "results"
    manual_archive(results, "mic-real", audio_files={"caller": "_live-audio/mic-real/caller.wav"})
    (results / "_live-audio" / "mic-real").mkdir(parents=True)
    (results / "_live-audio" / "mic-real" / "caller.wav").write_bytes(WAV)
    with TestClient(create_app(results)) as client:
        row = manual_row(client, "mic-real")
        url = f"/api/history/calls/{row['id']}/audio/{stream}"
        assert client.get(url).status_code in {404, 405}
