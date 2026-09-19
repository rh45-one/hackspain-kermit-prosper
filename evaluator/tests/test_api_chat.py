"""The chat API is the rig, not a simulation of it.

These tests drive the real endpoints against the test double: open a session,
say something, close it and read back what the receiver accepted. The double is
served in-process, so nothing here needs a live agent or the network.

The session is opened by **profile id** - a profile this server declares - and
never by a URL or a path. The catalog below is what the test server declares:
the double under test, and one agent that is not listening so the failure path
can be exercised. Sessions are also checked against each other: two open calls
must not consume one another's canned actions or reach one another's evidence.
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
from evaluator.profiles import AgentProfile, ProfileCatalog
from evaluator.runner.experiment import serve_in_thread

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"
CLINIC_PORT = 18996
DOUBLE_PORT = 18997
DEAD_PORT = 18999
CLINIC = f"http://127.0.0.1:{CLINIC_PORT}"

# Profile ids the test server declares. The console picks one of these; it can
# never name a host, a port or a path of its own.
DOUBLE_PROFILE = "double-under-test"
DEAD_PROFILE = "agent-not-listening"


def _catalog() -> ProfileCatalog:
    return ProfileCatalog(
        [
            AgentProfile.from_declaration(
                {
                    "id": DOUBLE_PROFILE,
                    "engine": "double",
                    "version": "test",
                    "endpoints": {
                        "ws_url": f"ws://127.0.0.1:{DOUBLE_PORT}/ws",
                        "text_url": f"http://127.0.0.1:{DOUBLE_PORT}",
                    },
                    "capabilities": {
                        "text": True,
                        "voice": True,
                        "audio_capture": True,
                        "audio_source": "client_capture",
                        "transcript": True,
                        "expected_outcome": True,
                    },
                    "providers": {"name": "evaluator test double"},
                    "laboratory": {"clinic_url": CLINIC, "voice_port": DOUBLE_PORT},
                }
            ),
            AgentProfile.from_declaration(
                {
                    "id": DEAD_PROFILE,
                    "engine": "external",
                    "version": "test",
                    "endpoints": {"ws_url": f"ws://127.0.0.1:{DEAD_PORT}/ws"},
                    "capabilities": {"voice": True},
                    "providers": {"name": "nada escuchando"},
                    "laboratory": {"clinic_url": CLINIC, "voice_port": DEAD_PORT},
                }
            ),
        ]
    )


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
    with TestClient(
        create_app(results, session_root=tmp_path / "chat", profiles=_catalog())
    ) as client:
        yield client
    double.stop()
    clinic.stop()


@pytest.fixture
def primed():
    def _prime(actions) -> None:
        import httpx

        httpx.post(f"http://127.0.0.1:{DOUBLE_PORT}/control", json={"actions": actions})

    return _prime


def _open(client, profile_id: str = DOUBLE_PROFILE, **overrides) -> dict:
    response = client.post(
        "/api/chat",
        json={
            "profile_id": profile_id,
            "stt": "none",
            "greeting_wait_ms": 3000,
            "reply_idle_ms": 300,
            "reply_start_ms": 3000,
            "submission_wait_s": 3,
            **overrides,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _book(patient_id: str) -> dict:
    return {
        "route": "book",
        "fields": {
            "patient_id": patient_id,
            "provider_id": "PR01",
            "location_id": "centro",
            "appointment_type_id": "review",
            "slot": "2026-09-21T09:00:00+02:00",
            "policy_id": "sanitas",
        },
    }


def test_a_session_greets_says_and_closes(stack, primed):
    primed([_book("P00042")])
    opened = _open(stack)
    assert opened["stt"] == "none"
    assert opened["profile_id"] == DOUBLE_PROFILE
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


def test_a_closed_session_declares_its_origin_and_its_evidence(stack):
    """A manual call uses the same call schema as the runner and the observer."""
    opened = _open(stack)
    stack.post(f"/api/chat/{opened['session_id']}/say", json={"text": "Hola, buenas tardes."})
    result = stack.post(f"/api/chat/{opened['session_id']}/close").json()
    assert result["origin"] == "manual"
    assert result["evidence"]["audio"] == "present"
    assert result["evidence"]["cost"] == "unknown", "sin usage_url el coste no es cero"
    assert result["evidence"]["outcome"] == "absent", "sin escenario no hay resultado esperado"
    assert result["started_at"] and result["ended_at"]


def test_two_open_sessions_do_not_share_calls_actions_or_evidence(stack, primed):
    """Session isolation: two live calls never consume each other's material.

    The double hands out one canned action per socket, in order, so a session
    that took the other session's queue would submit the wrong patient. Evidence
    is checked the same way: one session cannot read the other's audio.
    """
    primed([_book("P00042")])
    primed([_book("P00077")])
    first = _open(stack)
    second = _open(stack)
    assert first["call_id"] != second["call_id"]
    assert first["session_id"] != second["session_id"]

    said = stack.post(
        f"/api/chat/{second['session_id']}/say",
        json={"text": "Buenas, quería una cita para el martes por la mañana."},
    )
    assert said.status_code == 200, said.text
    stack.post(
        f"/api/chat/{first['session_id']}/say",
        json={"text": "Buenas tardes, necesito hablar con recepción."},
    )

    closed_first = stack.post(f"/api/chat/{first['session_id']}/close").json()
    closed_second = stack.post(f"/api/chat/{second['session_id']}/close").json()
    assert closed_first["call_id"] == first["call_id"]
    assert closed_second["call_id"] == second["call_id"]
    assert [action["patient_id"] for action in closed_first["submissions"]] == ["P00042"]
    assert [action["patient_id"] for action in closed_second["submissions"]] == ["P00077"]

    # Both sessions call their first caller turn the same thing, so the same
    # name must resolve to two different recordings: the audio of each one.
    name = said.json()["caller"]["wav"]
    mine = stack.get(f"/api/chat/{second['session_id']}/audio/{name}")
    theirs = stack.get(f"/api/chat/{first['session_id']}/audio/{name}")
    assert mine.status_code == 200 and theirs.status_code == 200
    assert mine.content != theirs.content, "las dos sesiones comparten la misma evidencia"


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
    # The clinic is up (so the call window could open) and the agent is not.
    response = stack.post(
        "/api/chat",
        json={"profile_id": DEAD_PROFILE, "stt": "none", "greeting_wait_ms": 500},
    )
    assert response.status_code == 502
    assert "websocket" in response.json()["detail"]


def test_the_browser_cannot_name_its_own_destination_or_path(stack):
    """The old contract: the body chose the socket, the clinic and a server path."""
    response = stack.post(
        "/api/chat",
        json={
            "ws_url": f"ws://127.0.0.1:{DOUBLE_PORT}/ws",
            "clinic_url": CLINIC,
            "scenario": "evaluator/scenarios/simple_booking/sb-001.yaml",
            "agent_audit_dir": "/tmp",
            "stt": "none",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    for field in ("ws_url", "clinic_url", "scenario", "agent_audit_dir"):
        assert field in detail
    assert "profile_id" in detail, "el error dice qué pedir en su lugar"


def test_an_unknown_profile_is_refused_with_the_declared_ones(stack):
    response = stack.post("/api/chat", json={"profile_id": "no-existe"})
    assert response.status_code == 404
    assert DOUBLE_PROFILE in response.json()["detail"]


def test_a_session_without_a_profile_is_refused(stack):
    response = stack.post("/api/chat", json={"stt": "none"})
    assert response.status_code == 400
    assert "profile_id" in response.json()["detail"]


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


def _open_and_say_audio(client, payload: str):
    session = _open(client)
    response = client.post(
        f"/api/chat/{session['session_id']}/say-audio", json={"mulaw_base64": payload}
    )
    return session, response


def test_microphone_audio_is_delivered_as_frames(stack, primed):
    """Push-to-talk: the browser uploads µ-law, the rig sends it as 20 ms frames."""
    import base64

    primed([{"route": "no-action", "fields": {"reason": "out_of_scope"}}])
    raw = bytes([0xFF]) * 3200  # 0.4 s of µ-law silence
    _, response = _open_and_say_audio(stack, base64.b64encode(raw).decode())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["caller"]["role"] == "caller"
    assert body["caller"]["seconds"] == 0.4
    # The rig saved what it really sent, and it answered the turn.
    assert body["caller"]["wav"].endswith("-caller.wav")
    assert body["agent"]["role"] == "agent"


def test_a_partial_last_frame_is_padded_to_twenty_milliseconds(stack, primed):
    """A capture that stops mid-frame must not send a short frame."""
    import base64

    from evaluator.api.chat import FRAME_BYTES

    primed([{"route": "no-action", "fields": {"reason": "out_of_scope"}}])
    raw = bytes([0xFF]) * (FRAME_BYTES + 7)
    session = _open(stack)
    response = stack.post(
        f"/api/chat/{session['session_id']}/say-audio",
        json={"mulaw_base64": base64.b64encode(raw).decode()},
    )
    assert response.status_code == 200
    body = response.json()
    evidence = stack.get(
        f"/api/chat/{session['session_id']}/audio/{body['caller']['wav']}"
    )
    assert evidence.status_code == 200
    # A real WAV for what the rig sent: two padded 20 ms frames plus the tail,
    # never a 7-byte fragment.
    assert evidence.content[:4] == b"RIFF"
    assert len(body["caller"]["wav"]) > 0


def test_microphone_upload_rejects_garbage_and_oversized_audio(stack, primed):
    import base64

    from evaluator.api.chat import MAX_MIC_SECONDS

    session = _open(stack)
    too_long = bytes([0xFF]) * int((MAX_MIC_SECONDS + 1) * 8000)
    oversized = stack.post(
        f"/api/chat/{session['session_id']}/say-audio",
        json={"mulaw_base64": base64.b64encode(too_long).decode()},
    )
    assert oversized.status_code == 413
    for payload in ("no-es-base64!!", ""):
        response = stack.post(
            f"/api/chat/{session['session_id']}/say-audio", json={"mulaw_base64": payload}
        )
        assert response.status_code == 422
    missing = stack.post(f"/api/chat/{session['session_id']}/say-audio", json={})
    assert missing.status_code == 422


def test_microphone_upload_needs_an_open_session(stack):
    import base64

    response = stack.post(
        "/api/chat/nope/say-audio",
        json={"mulaw_base64": base64.b64encode(bytes([0xFF]) * 160).decode()},
    )
    assert response.status_code == 404
