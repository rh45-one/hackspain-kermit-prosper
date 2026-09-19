"""The chat API is the rig, not a simulation of it.

These tests drive the real endpoints against the test double: open a session,
say something, close it and read back what the receiver accepted. The double is
served in-process, so nothing here needs a live agent or the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evaluator.api.app import create_app
from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app as create_clinic_app
from evaluator.harness.double_agent import create_app as create_double_app
from evaluator.runner.experiment import serve_in_thread

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"
CLINIC_PORT = 18996
DOUBLE_PORT = 18997
CLINIC = f"http://127.0.0.1:{CLINIC_PORT}"


@pytest.fixture
def stack(tmp_path):
    clinic = serve_in_thread(create_clinic_app(Dataset.load(DATASET)), "127.0.0.1", CLINIC_PORT)
    double = serve_in_thread(
        create_double_app(CLINIC, api_key="pk-local-eval"), "127.0.0.1", DOUBLE_PORT
    )
    results = tmp_path / "results"
    results.mkdir()
    # As a context manager, TestClient keeps ONE event loop for the whole test.
    # A live session holds a websocket bound to the loop that created it, which
    # is what uvicorn does in production and what a per-request portal cannot.
    with TestClient(create_app(results, session_root=tmp_path / "chat")) as client:
        yield client
    double.stop()
    clinic.stop()


@pytest.fixture
def primed():
    def _prime(actions) -> None:
        import httpx

        httpx.post(f"http://127.0.0.1:{DOUBLE_PORT}/control", json={"actions": actions})

    return _prime


def _open(client) -> dict:
    response = client.post(
        "/api/chat",
        json={
            "ws_url": f"ws://127.0.0.1:{DOUBLE_PORT}/ws",
            "clinic_url": CLINIC,
            "stt": "none",
            "greeting_wait_ms": 3000,
            "reply_idle_ms": 300,
            "reply_start_ms": 3000,
            "submission_wait_s": 3,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_session_greets_says_and_closes(stack, primed):
    primed(
        [
            {
                "route": "book",
                "fields": {
                    "patient_id": "P00042",
                    "provider_id": "PR01",
                    "location_id": "centro",
                    "appointment_type_id": "review",
                    "slot": "2026-09-21T09:00:00+02:00",
                    "policy_id": "sanitas",
                },
            }
        ]
    )
    opened = _open(stack)
    assert opened["stt"] == "none"
    assert opened["greeting"], "el doble saluda en cuanto abre"

    said = stack.post(
        f"/api/chat/{opened['session_id']}/say",
        json={
            # Long enough to be judgeable: below two seconds of caller speech the
            # diagnosis deliberately says nothing rather than blame the agent.
            "text": (
                "Hola, buenas tardes, quería pedir una cita de medicina general "
                "para el martes por la mañana, si es posible."
            )
        },
    )
    assert said.status_code == 200, said.text
    turn = said.json()
    assert turn["caller"]["role"] == "caller"
    assert turn["agent"]["role"] == "agent"
    assert turn["agent"]["wav"], "el audio del agente queda como evidencia"
    assert turn["agent"]["text"] == "", "sin STT configurado no se inventa transcripción"

    audio = stack.get(f"/api/chat/{opened['session_id']}/audio/{turn['agent']['wav']}")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"

    closed = stack.post(f"/api/chat/{opened['session_id']}/close")
    assert closed.status_code == 200, closed.text
    result = closed.json()
    assert result["frames_sent"] > 0
    assert result["submissions"], "el doble envía la reserva al receptor local"
    assert result["diagnosis"]["kind"] == "unavailable", "sin ruta de auditoría no se puede culpar al agente"
    assert result["diagnosis"]["blocks_model_scoring"] is False


def test_a_closed_session_cannot_be_used_again(stack):
    opened = _open(stack)
    assert stack.post(f"/api/chat/{opened['session_id']}/close").status_code == 200
    again = stack.post(f"/api/chat/{opened['session_id']}/say", json={"text": "hola"})
    assert again.status_code == 409


def test_unknown_session_is_404(stack):
    assert stack.post("/api/chat/nope/say", json={"text": "hola"}).status_code == 404
    assert stack.post("/api/chat/nope/close").status_code == 404


def test_small_refusals_do_not_need_their_own_session(stack):
    opened = _open(stack)
    session_id = opened["session_id"]
    assert stack.post(f"/api/chat/{session_id}/say", json={"text": "  "}).status_code == 422
    escaped = stack.get(f"/api/chat/{session_id}/audio/..%2F..%2Fetc%2Fpasswd")
    assert escaped.status_code in (400, 404)
    assert stack.post(f"/api/chat/{session_id}/close").status_code == 200


def test_an_unreachable_agent_is_reported_not_hidden(stack):
    # The clinic is up (so the call window opens) and the agent is not.
    response = stack.post(
        "/api/chat",
        json={
            "ws_url": "ws://127.0.0.1:18999/ws",
            "clinic_url": CLINIC,
            "stt": "none",
            "greeting_wait_ms": 500,
        },
    )
    assert response.status_code == 502
    assert "websocket" in response.json()["detail"]


def test_the_console_is_served_when_a_web_dir_is_given(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>consola</html>", encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    client = TestClient(create_app(results, web_dir=web, session_root=tmp_path / "chat"))
    assert "consola" in client.get("/").text


def test_the_console_is_optional(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    client = TestClient(create_app(results, session_root=tmp_path / "chat"))
    assert client.get("/").status_code == 404


def test_manifest_is_read_for_the_console(tmp_path):
    results = tmp_path / "results"
    run = results / "run-1"
    run.mkdir(parents=True)
    (run / "cases.jsonl").write_text("", encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({"experiment": "smoke"}), encoding="utf-8")
    client = TestClient(create_app(results, session_root=tmp_path / "chat"))
    rows = client.get("/api/runs").json()
    assert rows[0]["experiment"] == "smoke"
    assert rows[0]["cases"] == 0
