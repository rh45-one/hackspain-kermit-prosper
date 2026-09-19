"""The duplex session: the same wire as `dial()`, without a precomputed script.

`dial()` is scripted playback; a manual chat needs to send when the person
types and listen while the agent speaks. These tests pin that the shared
implementation really is shared: the session and `dial()` account for the same
frames, and the streaming surface behaves (barge-in, silence cut-off, teardown)
against the double agent over a real websocket.
"""
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from pathlib import Path

import httpx
import pytest
import websockets

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app as create_clinic_app
from evaluator.harness.double_agent import create_app as create_double_app
from evaluator.harness.wsclient import CallSession, dial, silence
from evaluator.runner.experiment import serve_in_thread

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"
KEY = "pk-local-eval"
CLINIC = "http://127.0.0.1:18992"
WS_URL = "ws://127.0.0.1:18993/ws"

BOOK = {
    "action": "BOOK",
    "patient_id": "P00042",
    "provider_id": "PR01",
    "location_id": "centro",
    "appointment_type_id": "review",
    "slot": "2026-09-21T09:00:00+02:00",
    "policy_id": "sanitas",
}


@pytest.fixture
def rig():
    dataset = Dataset.load(DATASET)
    clinic = serve_in_thread(create_clinic_app(dataset, api_key=KEY), "127.0.0.1", 18992)
    double = serve_in_thread(
        create_double_app(CLINIC, api_key=KEY), "127.0.0.1", 18993
    )
    yield
    double.stop()
    clinic.stop()


async def _open_call(call_id: str) -> None:
    async with httpx.AsyncClient(base_url=CLINIC) as http:
        await http.post("/eval/calls", json={"call_id": call_id})


async def _prime_double(actions: list[dict] | None) -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:18993") as double:
        await double.post("/control", json={"actions": actions})


def _book_action() -> list[dict]:
    return [{**{k: v for k, v in BOOK.items() if k != "action"}, "route": "book"}]


async def test_session_streams_agent_audio_and_records_latency(rig):
    call_id = uuid.uuid4().hex
    await _open_call(call_id)
    await _prime_double(_book_action())

    async with CallSession(WS_URL, call_id, from_number="+34612345678") as session:
        barged = await session.send_frames(silence(300))
        audio = await session.drain_audio(idle_ms=300, max_ms=3000)
        evidence = await session.close()

    assert barged is False
    assert evidence.error is None
    assert evidence.frames_sent == len(silence(300))
    assert evidence.frames_received > 0
    assert evidence.first_audio_ms is not None
    assert evidence.stopped_at > evidence.connected_at
    assert audio
    assert len(audio) % 160 == 0
    assert evidence.turn_latencies_ms and evidence.turn_latencies_ms[0] is not None


async def test_inbound_iterator_yields_agent_audio(rig):
    call_id = uuid.uuid4().hex
    await _open_call(call_id)
    await _prime_double(_book_action())

    session = CallSession(WS_URL, call_id)
    await session.open()
    try:
        await session.send_frames(silence(300))
        first = await asyncio.wait_for(anext(session.inbound()), timeout=5)
    finally:
        await session.close()

    assert isinstance(first, bytes)
    assert len(first) % 160 == 0


async def test_session_barges_out_and_settles_the_agent_tail(rig):
    call_id = uuid.uuid4().hex
    await _open_call(call_id)
    await _prime_double(_book_action())

    session = CallSession(WS_URL, call_id)
    await session.open()
    try:
        # First utterance lets the double start talking...
        await session.send_frames(silence(400))
        # ...the second one is long and interrupts as soon as it hears audio.
        barged = await session.send_frames(silence(20000), interrupt_on_agent_audio=True, turn=1)
        evidence = await session.close()
    finally:
        session.finalize()

    assert barged is True
    assert len(evidence.interrupts) == 1
    assert evidence.interrupts[0]["turn"] == 1
    assert "agent_tail_ms" in evidence.interrupts[0]
    # The caller stopped early instead of playing all 1000 frames.
    assert evidence.frames_sent < len(silence(20000))


async def _silent_agent(ws) -> None:
    """A peer that completes the handshake and never speaks."""
    async for _ in ws:
        pass


async def _late_speaker(ws, delay_s: float = 1.0) -> None:
    """A peer that stays quiet and then speaks once, like a late greeting."""

    async def _speak_later() -> None:
        await asyncio.sleep(delay_s)
        payload = base64.b64encode(b"\xff" * 160).decode()
        await ws.send(json.dumps({"event": "media", "media": {"payload": payload}}))

    task = asyncio.create_task(_speak_later())
    try:
        async for _ in ws:
            pass
    finally:
        task.cancel()


async def test_first_wait_is_what_makes_a_late_greeting_arrive():
    """Waiting `idle_ms` for the first frame is what made the caller talk over it."""
    async with websockets.serve(_late_speaker, "127.0.0.1", 18995):
        impatient = CallSession("ws://127.0.0.1:18995/ws", uuid.uuid4().hex)
        await impatient.open()
        try:
            ignored = await impatient.drain_audio(idle_ms=150, max_ms=8000)
        finally:
            await impatient.close()

        patient = CallSession("ws://127.0.0.1:18995/ws", uuid.uuid4().hex)
        await patient.open()
        try:
            greeted = await patient.drain_audio(idle_ms=150, first_wait_ms=4000, max_ms=8000)
        finally:
            await patient.close()

    assert ignored == b""
    assert len(greeted) == 160


async def test_drain_audio_gives_up_when_the_agent_is_quiet():
    async with websockets.serve(_silent_agent, "127.0.0.1", 18994):
        session = CallSession("ws://127.0.0.1:18994/ws", uuid.uuid4().hex)
        await session.open()
        try:
            await session.send_frames(silence(40))
            started = asyncio.get_running_loop().time()
            audio = await session.drain_audio(idle_ms=200, max_ms=5000)
            elapsed = asyncio.get_running_loop().time() - started
        finally:
            await session.close()

    assert audio == b""
    assert elapsed < 2.0  # it stopped on silence, not on the max wait
    assert session.evidence.frames_received == 0


async def test_session_matches_dial_frame_accounting(rig):
    frames = silence(200)
    dial_call, session_call = uuid.uuid4().hex, uuid.uuid4().hex
    await _open_call(dial_call)
    await _open_call(session_call)
    await _prime_double(_book_action())

    scripted = await dial(WS_URL, dial_call, [frames], after_send_idle_s=0.3)

    session = CallSession(WS_URL, session_call)
    await session.open()
    try:
        await session.send_frames(frames)
        await asyncio.sleep(0.3)
    finally:
        streamed = await session.close()

    assert scripted.error is None and streamed.error is None
    assert scripted.frames_sent == streamed.frames_sent == len(frames)
    assert scripted.first_audio_ms is not None and streamed.first_audio_ms is not None
    assert streamed.frames_received > 0


async def test_open_failure_is_recorded_and_raised():
    session = CallSession("ws://127.0.0.1:18999/ws", uuid.uuid4().hex, open_timeout_s=2)
    with pytest.raises(Exception) as error:
        await session.open()
    assert session.evidence.error is not None
    assert type(error.value).__name__ in session.evidence.error
    await session.close()


async def test_close_before_open_is_safe():
    session = CallSession(WS_URL, uuid.uuid4().hex)
    evidence = await session.close()
    assert evidence.error is None
    assert evidence.frames_sent == 0
