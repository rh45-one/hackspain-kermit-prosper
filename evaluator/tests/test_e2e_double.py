"""End-to-end rig check: harness caller -> double agent -> clinic receiver.

Proves the evaluator itself before a real agent is plugged in: the wire
handshake carries call_id, the double submits after stop, the receiver
records it, and the scorer sees the record.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app as create_clinic_app
from evaluator.compare import compare
from evaluator.harness.double_agent import create_app as create_double_app
from evaluator.harness.wsclient import PlayTurn, dial, load_audio, silence
from evaluator.runner.experiment import serve_in_thread

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"
KEY = "pk-local-eval"

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
    clinic = serve_in_thread(create_clinic_app(dataset, api_key=KEY), "127.0.0.1", 18990)
    double = serve_in_thread(
        create_double_app("http://127.0.0.1:18990", api_key=KEY), "127.0.0.1", 18991
    )
    yield
    double.stop()
    clinic.stop()


class TestAudioHelpers:
    def test_silence_frame_count(self):
        assert len(silence(1000)) == 50
        assert all(len(f) == 160 for f in silence(100))

    def test_load_audio_pads_tail(self, tmp_path):
        path = tmp_path / "clip.raw"
        path.write_bytes(b"\x01" * 200)
        frames = load_audio(path)
        assert len(frames) == 2
        assert len(frames[1]) == 160


class TestDoubleE2E:
    async def test_double_submits_and_scores(self, rig):
        call_id = uuid.uuid4().hex
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18990") as http:
            await http.post("/eval/calls", json={"call_id": call_id})
            async with httpx.AsyncClient(base_url="http://127.0.0.1:18991") as d:
                await d.post(
                    "/control",
                    json={"actions": [{"route": "book", "fields": {k: v for k, v in BOOK.items() if k != "action"}}]},
                )
            ev = await dial(
                "ws://127.0.0.1:18991/ws",
                call_id,
                [silence(300)],
                from_number="+34612345678",
                after_send_idle_s=0.3,
            )
            assert ev.error is None
            assert ev.frames_received > 0  # the double talks back
            assert ev.first_audio_ms is not None

            await http.post(f"/eval/calls/{call_id}/close")
            record = (await http.get(f"/eval/calls/{call_id}/record")).json()

        cmp = compare(record["actions"], [[BOOK]])
        assert cmp.passed

    async def test_silent_double_fails_missing_record(self, rig):
        call_id = uuid.uuid4().hex
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18990") as http:
            await http.post("/eval/calls", json={"call_id": call_id})
            async with httpx.AsyncClient(base_url="http://127.0.0.1:18991") as d:
                await d.post("/control", json={"actions": None})
            ev = await dial(
                "ws://127.0.0.1:18991/ws",
                call_id,
                [silence(200)],
                after_send_idle_s=0.3,
            )
            assert ev.error is None
            await http.post(f"/eval/calls/{call_id}/close")
            record = (await http.get(f"/eval/calls/{call_id}/record")).json()

        cmp = compare(record["actions"], [[BOOK]])
        assert not cmp.passed and cmp.failure_signal == "missing_record"

    async def test_wrong_field_scores_record_mismatch(self, rig):
        call_id = uuid.uuid4().hex
        bad = {**BOOK, "policy_id": "asisa"}
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18990") as http:
            await http.post("/eval/calls", json={"call_id": call_id})
            async with httpx.AsyncClient(base_url="http://127.0.0.1:18991") as d:
                await d.post(
                    "/control",
                    json={"actions": [{"route": "book", "fields": {k: v for k, v in bad.items() if k != "action"}}]},
                )
            await dial(
                "ws://127.0.0.1:18991/ws",
                call_id,
                [silence(200)],
                after_send_idle_s=0.3,
            )
            await http.post(f"/eval/calls/{call_id}/close")
            record = (await http.get(f"/eval/calls/{call_id}/record")).json()

        cmp = compare(record["actions"], [[BOOK]])
        assert not cmp.passed and cmp.failure_signal == "record_mismatch"
        assert any(d.field == "policy_id" for d in cmp.field_diffs)


class TestWireEvidence:
    async def test_captures_both_audio_directions(self, rig):
        call_id = uuid.uuid4().hex
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18990") as http:
            await http.post("/eval/calls", json={"call_id": call_id})
            ev = await dial(
                "ws://127.0.0.1:18991/ws",
                call_id,
                [silence(200)],
                after_send_idle_s=0.3,
            )
            assert ev.error is None
            assert len(ev.agent_audio) > 0  # the double talks back in µ-law
            assert len(ev.caller_audio) > 0
            assert len(ev.caller_audio) == ev.frames_sent * 160

    async def test_barge_in_stops_caller_utterance(self, rig):
        call_id = uuid.uuid4().hex
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18990") as http:
            await http.post("/eval/calls", json={"call_id": call_id})
            # Turn 0 settles the stream; turn 1 is long and interrupts on
            # the double's constant talkback audio.
            ev = await dial(
                "ws://127.0.0.1:18991/ws",
                call_id,
                [
                    PlayTurn(silence(200)),
                    PlayTurn(silence(20000), interrupt_on_agent_audio=True),
                ],
                after_send_idle_s=0.3,
            )
            assert ev.error is None
            assert len(ev.interrupts) == 1
            assert ev.interrupts[0]["turn"] == 1
            assert "agent_tail_ms" in ev.interrupts[0]
            # Barge-in cut the 20 s utterance far short of its 1000 frames.
            assert ev.frames_sent < 1000


class TestPerCallControl:
    async def test_two_concurrent_calls_get_own_actions(self, rig):
        call_a, call_b = uuid.uuid4().hex, uuid.uuid4().hex
        bad = {**BOOK, "policy_id": "asisa"}
        fields = lambda a: {k: v for k, v in a.items() if k != "action"}
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18990") as http:
            await http.post("/eval/calls", json={"call_id": call_a})
            await http.post("/eval/calls", json={"call_id": call_b})
            async with httpx.AsyncClient(base_url="http://127.0.0.1:18991") as d:
                await d.post(
                    "/control",
                    json={"call_id": call_a,
                          "actions": [{"route": "book", "fields": fields(BOOK)}]},
                )
                await d.post(
                    "/control",
                    json={"call_id": call_b,
                          "actions": [{"route": "book", "fields": fields(bad)}]},
                )
            import asyncio

            ev_a, ev_b = await asyncio.gather(
                dial("ws://127.0.0.1:18991/ws", call_a, [silence(200)],
                     after_send_idle_s=0.3),
                dial("ws://127.0.0.1:18991/ws", call_b, [silence(200)],
                     after_send_idle_s=0.3),
            )
            assert ev_a.error is None and ev_b.error is None
            await http.post(f"/eval/calls/{call_a}/close")
            await http.post(f"/eval/calls/{call_b}/close")
            rec_a = (await http.get(f"/eval/calls/{call_a}/record")).json()
            rec_b = (await http.get(f"/eval/calls/{call_b}/record")).json()

        # No cross-contamination: A booked correctly, B booked the bad policy.
        assert compare(rec_a["actions"], [[BOOK]]).passed
        cmp_b = compare(rec_b["actions"], [[BOOK]])
        assert not cmp_b.passed and any(
            d.field == "policy_id" for d in cmp_b.field_diffs
        )


class TestUsage:
    async def test_usage_endpoint_reports_cost(self, rig):
        call_id = uuid.uuid4().hex
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18990") as http:
            await http.post("/eval/calls", json={"call_id": call_id})
            async with httpx.AsyncClient(base_url="http://127.0.0.1:18991") as d:
                await d.post(
                    "/control",
                    json={"call_id": call_id,
                          "actions": [{"route": "book", "fields":
                                       {k: v for k, v in BOOK.items() if k != "action"}}]},
                )
            await dial("ws://127.0.0.1:18991/ws", call_id, [silence(200)],
                       after_send_idle_s=0.3)
            async with httpx.AsyncClient(base_url="http://127.0.0.1:18991") as d:
                usage = (await d.get(f"/usage/calls/{call_id}")).json()
            assert usage["call_id"] == call_id
            assert usage["cost"] is not None and usage["cost"] > 0
            assert usage["usage"]["submissions"] == 1

    async def test_usage_unknown_call(self, rig):
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18991") as d:
            usage = (await d.get("/usage/calls/nonexistent")).json()
        assert usage["cost"] is None  # unknown ≠ zero
