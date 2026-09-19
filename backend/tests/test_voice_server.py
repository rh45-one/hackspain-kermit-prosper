"""Offline server tests: /healthz, the /ws handshake, and concurrent sockets.

The endpoint runs the real serializer, transport, pipeline and runner, but
``build_worker`` is patched to its ``with_services=False`` mode, so no
Deepgram, ElevenLabs, Helmcode, Prosper or ngrok traffic is possible.
Flushes are wrapped by a recorder that keeps the real, keyless behaviour
(no outbound POSTs without PROSPER_API_KEY).

Timing note: a harness call keeps the socket open for a whole conversation
before sending `stop` and closing. In tests we still close as soon as the
identity is known (watched via the per-call audit file), which is
deterministic; closing microseconds after connect would race pipeline
startup and is not a scenario the harness produces.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from agent.config import Settings
from agent.voice import server as server_module

CONCURRENT_SOCKETS = 20


class SettingsFixture(Settings):
    def __init__(self, data_dir: str) -> None:
        super().__init__(
            prosper_api_key="",
            data_dir=data_dir,
            log_level="WARNING",
        )


@pytest.fixture()
def flushed():
    """Recorder around flush_call: captures each flushed CallContext."""

    from agent.voice.flush import flush_call as real_flush

    class Recorder:
        def __init__(self) -> None:
            self.contexts: list = []
            self.event = threading.Event()

        async def __call__(self, ctx, settings) -> None:
            await real_flush(ctx, settings)
            self.contexts.append(ctx)
            self.event.set()

    return Recorder()


@pytest.fixture()
def client(monkeypatch, tmp_path, flushed):
    settings = SettingsFixture(str(tmp_path / "data"))
    monkeypatch.setattr(server_module, "app_settings", settings)

    real_build = server_module.build_worker

    def lightweight_build(transport, ctx, app_settings, **kwargs):
        return real_build(transport, ctx, app_settings, with_services=False)

    monkeypatch.setattr(server_module, "build_worker", lightweight_build)
    monkeypatch.setattr(server_module, "flush_call", flushed)

    with TestClient(server_module.app) as test_client:
        yield test_client


def calls_dir_of(client, tmp_path) -> Path:
    return Path(server_module.app_settings.data_dir) / "calls"


def start_message(i: int, with_phone: bool = True) -> dict:
    call_id = f"CA-concurrent-{i}"
    params: dict = {"call_id": call_id}
    if with_phone:
        params["from_number"] = f"+34600000{i:03d}"
    return {
        "event": "start",
        "start": {
            "callSid": call_id,
            "streamSid": f"SM-{i}",
            "customParameters": params,
        },
        "sequenceNumber": "2",
    }


def wait_for(condition, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def wait_until_call_known(calls_dir: Path, call_id: str) -> None:
    """Block until the server has bound callSid (audit file moved) or fail."""
    assert wait_for(lambda: (calls_dir / f"{call_id}.jsonl").exists()), (
        f"server never processed start for {call_id}"
    )


def test_healthz(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_browser_call_page_and_assets_are_served(client):
    page = client.get("/call")

    assert page.status_code == 200
    assert "Call the scheduling agent" in page.text
    assert 'id="call-button"' in page.text
    assert client.get("/call/app.js").status_code == 200
    assert client.get("/call/mic-worklet.js").status_code == 200
    assert client.get("/call/styles.css").status_code == 200


def test_websocket_handshake_connected_start_stop(client, flushed, tmp_path):
    """The full wire handshake: connected -> start -> stop -> close."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(start_message(1))
        wait_until_call_known(calls_dir_of(client, tmp_path), "CA-concurrent-1")
        ws.send_json({"event": "stop", "streamSid": "SM-1"})

    assert wait_for(lambda: len(flushed.contexts) == 1)
    ctx = flushed.contexts[0]
    # start.callSid becomes the call id used everywhere, including submissions.
    assert ctx.call_id == "CA-concurrent-1"
    assert ctx.stream_sid == "SM-1"
    assert ctx.from_number == "+34600000001"
    assert ctx.stopped is True
    # The offline flush falls back to the mandatory no-action record.
    assert ctx.queued_actions == [{"route": "no-action", "reason": "out_of_scope"}]


def test_demo_websocket_uses_pipeline_without_submission(client, flushed, tmp_path):
    with client.websocket_connect("/ws/demo") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(start_message(21, with_phone=False))
        wait_until_call_known(calls_dir_of(client, tmp_path), "CA-concurrent-21")
        ws.send_json({"event": "stop", "streamSid": "SM-21"})

    assert wait_for(lambda: len(flushed.contexts) == 1)
    ctx = flushed.contexts[0]
    assert ctx.call_id == "CA-concurrent-21"
    assert ctx.submit_actions is False
    assert ctx.submitted is True
    assert ctx.queued_actions == []


def test_websocket_without_from_number(client, flushed, tmp_path):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(start_message(2, with_phone=False))
        wait_until_call_known(calls_dir_of(client, tmp_path), "CA-concurrent-2")

    assert wait_for(lambda: len(flushed.contexts) == 1)
    ctx = flushed.contexts[0]
    assert ctx.call_id == "CA-concurrent-2"
    assert ctx.from_number is None  # withheld caller id stays a missing hint


def test_each_socket_gets_its_own_call_context(client, flushed, tmp_path):
    """Two sequential calls must not share conversation state."""
    for i in (3, 4):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            ws.send_json(start_message(i))
            wait_until_call_known(calls_dir_of(client, tmp_path), f"CA-concurrent-{i}")

    assert wait_for(lambda: len(flushed.contexts) == 2)
    ids = [ctx.call_id for ctx in flushed.contexts]
    assert ids == ["CA-concurrent-3", "CA-concurrent-4"]


def test_twenty_concurrent_handshakes(client, flushed, tmp_path):
    """Run All opens ten sockets; problem 2 bursts twenty."""
    calls_dir = calls_dir_of(client, tmp_path)
    sessions = []
    for i in range(CONCURRENT_SOCKETS):
        ws = client.websocket_connect("/ws")
        ws.__enter__()
        sessions.append((i, ws))

    try:
        for i, ws in sessions:
            ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            ws.send_json(start_message(i))
        # Every socket must bind its own identity: no shared context anywhere.
        for i in range(CONCURRENT_SOCKETS):
            wait_until_call_known(calls_dir, f"CA-concurrent-{i}")
    finally:
        for _, ws in sessions:
            try:
                ws.__exit__(None, None, None)
            except Exception as exc:  # noqa: BLE001 - teardown best effort
                logger.debug("closing socket {} failed: {}", _, exc)

    assert wait_for(lambda: len(flushed.contexts) == CONCURRENT_SOCKETS)
    ids = sorted(ctx.call_id for ctx in flushed.contexts)
    assert ids == sorted(f"CA-concurrent-{i}" for i in range(CONCURRENT_SOCKETS))
    assert len({id(ctx) for ctx in flushed.contexts}) == CONCURRENT_SOCKETS
