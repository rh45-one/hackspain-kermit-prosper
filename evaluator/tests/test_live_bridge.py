"""Exercise the real duplex bridge, including clear, resumed audio and failures.

Every failure mode names its own cause: a browser-side protocol error must not
be reported as an unavailable agent, and a transport failure must never echo the
exception text (it can carry the WebSocket URL and its credentials).
"""
import base64
import json
import socket

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from evaluator.api import live
from evaluator.api.app import create_app
from evaluator.profiles import AgentProfile, ProfileCatalog
from evaluator.runner.experiment import serve_in_thread


def silent_call_window(monkeypatch):
    """Replace the clinic/submission window: this test owns only the bridge."""

    async def no_op(*args, **kwargs):
        return {}

    monkeypatch.setattr(live, "open_call_window", no_op)
    monkeypatch.setattr(live, "close_call_window", no_op)
    monkeypatch.setattr(live, "wait_for_actions", no_op)


def idle_agent(recorded):
    """An agent that accepts the handshake and stays connected until closed."""
    agent = FastAPI()

    @agent.websocket("/ws")
    async def voice(socket: WebSocket):
        await socket.accept()
        while True:
            try:
                recorded.append(await socket.receive_json())
            except WebSocketDisconnect:
                return

    return agent


def voice_profile(ws_url):
    return AgentProfile.from_declaration({
        "id": "test-voice", "engine": "external", "version": "test",
        "endpoints": {"ws_url": ws_url},
        "capabilities": {"voice": True}, "providers": {"name": "test server"},
    })


def dead_port():
    """A port nothing listens on, so a connect attempt is refused."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def archive(tmp_path):
    return json.loads(next((tmp_path / "_manual-calls").glob("*.json")).read_text())


def test_microphone_duplex_clear_resume_and_archive(tmp_path, monkeypatch):
    silent_call_window(monkeypatch)
    agent = FastAPI()
    recorded = []

    @agent.websocket("/ws")
    async def voice(socket: WebSocket):
        await socket.accept()
        assert (await socket.receive_json())["event"] == "connected"
        start = await socket.receive_json()
        recorded.append(start)
        frame = await socket.receive_json()
        recorded.append(frame)
        assert len(base64.b64decode(frame["media"]["payload"])) == 160
        await socket.send_json({"event": "clear"})
        await socket.send_json({"event": "media", "media": {"payload": base64.b64encode(b"\x7f" * 160).decode()}})
        recorded.append(await socket.receive_json())
        await socket.close()

    server = serve_in_thread(agent, "127.0.0.1", 0)
    port = server.listener.getsockname()[1]
    profile = voice_profile(f"ws://127.0.0.1:{port}/ws")
    try:
        with TestClient(create_app(tmp_path, profiles=ProfileCatalog([profile]))) as client:
            with client.websocket_connect("/api/live/test-voice") as socket:
                assert socket.receive_json()["event"] == "ready"
                socket.send_bytes(b"\xff" * 160)
                assert socket.receive_json()["event"] == "clear"
                assert socket.receive_json()["event"] == "media"
                socket.send_text("stop")
                finished = socket.receive_json()
                assert finished["event"] == "finished" and finished["error"] is None
            archived = archive(tmp_path)
            assert archived["evidence"]["audio"] == "present"
            assert archived["evidence"]["transcript"] == "absent"
            assert set(archived["audio_files"]) == {"caller", "agent"}
            assert recorded[-1]["event"] == "stop"
            client.post("/api/history/import")
            row = client.get("/api/history/calls?origin=manual").json()["items"][0]
            assert client.get(f"/api/history/calls/{row['id']}/audio/agent").content.startswith(b"RIFF")
    finally:
        server.stop()


def test_live_unknown_profile_is_visible_failure(tmp_path):
    with TestClient(create_app(tmp_path)) as client, client.websocket_connect("/api/live/unknown") as socket:
        result = socket.receive_json()
        assert result["event"] == "finished"
        assert result["error"]
    assert not (tmp_path / "_manual-calls").exists()


def test_live_rejects_cross_origin_browser_before_accepting(tmp_path):
    """A page on another origin must not be able to open the microphone bridge."""
    with (
        TestClient(create_app(tmp_path)) as client,
        pytest.raises(WebSocketDisconnect) as denied,
        client.websocket_connect("/api/live/unknown", headers={"origin": "http://evil.example"}),
    ):
        pass
    assert denied.value.code == 1008
    assert not (tmp_path / "_manual-calls").exists()


def test_live_same_origin_browser_is_not_rejected(tmp_path):
    """The guard must not block the laboratory's own page."""
    with TestClient(create_app(tmp_path)) as client, client.websocket_connect(
        "/api/live/unknown", headers={"origin": "http://testserver"}
    ) as socket:
        assert socket.receive_json()["event"] == "finished"


@pytest.mark.parametrize("send", [lambda s: s.send_text("hola"), lambda s: s.send_bytes(b"\xff" * 10)])
def test_live_protocol_error_is_not_reported_as_agent_failure(tmp_path, monkeypatch, send):
    """A malformed frame is the browser's fault, and the archive must say so."""
    silent_call_window(monkeypatch)
    recorded = []
    server = serve_in_thread(idle_agent(recorded), "127.0.0.1", 0)
    port = server.listener.getsockname()[1]
    profile = voice_profile(f"ws://127.0.0.1:{port}/ws")
    try:
        with (
            TestClient(create_app(tmp_path, profiles=ProfileCatalog([profile]))) as client,
            client.websocket_connect("/api/live/test-voice") as socket,
        ):
            assert socket.receive_json()["event"] == "ready"
            send(socket)
            finished = socket.receive_json()
            assert finished["event"] == "finished"
            assert finished["error"] == live.PROTOCOL_ERROR
        assert archive(tmp_path)["transport_error"] == live.PROTOCOL_ERROR
    finally:
        server.stop()


def test_live_time_limit_is_reported_and_archived(tmp_path, monkeypatch):
    silent_call_window(monkeypatch)
    monkeypatch.setattr(live, "MAX_CALL_SECONDS", 0.2)
    recorded = []
    server = serve_in_thread(idle_agent(recorded), "127.0.0.1", 0)
    port = server.listener.getsockname()[1]
    profile = voice_profile(f"ws://127.0.0.1:{port}/ws")
    try:
        with (
            TestClient(create_app(tmp_path, profiles=ProfileCatalog([profile]))) as client,
            client.websocket_connect("/api/live/test-voice") as socket,
        ):
            assert socket.receive_json()["event"] == "ready"
            socket.send_bytes(b"\xff" * 160)
            finished = socket.receive_json()
            assert finished["event"] == "finished"
            assert finished["error"] == live.TIME_LIMIT_ERROR
        assert archive(tmp_path)["transport_error"] == live.TIME_LIMIT_ERROR
    finally:
        server.stop()


def test_live_transport_failure_hides_the_exception(tmp_path, monkeypatch):
    """The refusal message must not echo a URL that may embed credentials."""
    silent_call_window(monkeypatch)
    profile = voice_profile(f"ws://user:secret@127.0.0.1:{dead_port()}/ws")
    with (
        TestClient(create_app(tmp_path, profiles=ProfileCatalog([profile]))) as client,
        client.websocket_connect("/api/live/test-voice") as socket,
    ):
        # The agent is unreachable, so the bridge never reaches `ready`.
        finished = socket.receive_json()
        assert finished["event"] == "finished"
        assert finished["error"] == live.TRANSPORT_ERROR
        assert "secret" not in json.dumps(finished)
    archived = archive(tmp_path)
    assert archived["transport_error"] == live.TRANSPORT_ERROR
    assert "secret" not in json.dumps(archived)
