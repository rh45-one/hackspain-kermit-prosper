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
from evaluator.harness.wsclient import dial, load_audio, silence
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
                silence(300),
                from_number="+34612345678",
                after_send_idle_s=0.3,
            )
            assert ev.error is None
            assert ev.frames_received > 0  # the double talks back

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
                silence(200),
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
                silence(200),
                after_send_idle_s=0.3,
            )
            await http.post(f"/eval/calls/{call_id}/close")
            record = (await http.get(f"/eval/calls/{call_id}/record")).json()

        cmp = compare(record["actions"], [[BOOK]])
        assert not cmp.passed and cmp.failure_signal == "record_mismatch"
        assert any(d.field == "policy_id" for d in cmp.field_diffs)
