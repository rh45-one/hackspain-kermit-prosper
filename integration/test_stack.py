"""Local contracts: real clinic, agent transport, flush and FrontDesk API.

Run from the root: PYTHONPATH=evaluator/src uv run --project backend pytest integration -q
Speech providers are disabled only inside the WebSocket fixture.
"""
import asyncio
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from agent.brain import tools
from agent.brain.tools import ToolBox
from agent.clinic.cache import CatalogueCache
from agent.clinic.client import ProsperClient
from agent.config import Settings
from agent.ops import frontdesk
from agent.serve import app
from agent.voice import server
from agent.voice.context import CallContext
from agent.voice.flush import flush_call
from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app
from evaluator.compare import compare
from evaluator.harness.wsclient import dial, silence
from evaluator.runner.experiment import serve_in_thread

DATASET = Path(__file__).resolve().parents[1] / "evaluator/data/clinic_dataset.json"
KEY = "pk-local-eval"


@pytest.fixture
def stack(tmp_path, monkeypatch, unused_tcp_port_factory):
    clinic_port = unused_tcp_port_factory()
    agent_port = unused_tcp_port_factory()
    config = Settings(
        _env_file=None,
        prosper_api_base_url=f"http://127.0.0.1:{clinic_port}",
        prosper_api_key=KEY, typesafe_api_key="", data_dir=str(tmp_path),
    )
    monkeypatch.setattr(server, "app_settings", config)
    monkeypatch.setattr(frontdesk, "settings", lambda: config)
    real_build = server.build_worker

    def without_providers(transport, ctx, settings):
        return real_build(transport, ctx, settings, with_services=False)

    monkeypatch.setattr(server, "build_worker", without_providers)
    clinic = serve_in_thread(create_app(Dataset.load(DATASET)), "127.0.0.1", clinic_port)
    agent = serve_in_thread(app, "127.0.0.1", agent_port)
    try:
        yield config, f"http://127.0.0.1:{agent_port}"
    finally:
        agent.stop()
        clinic.stop()


class ToolResult:
    def __init__(self):
        self.value: dict[str, object] = {}

    async def result_callback(self, value: dict[str, object]):
        self.value = value
        assert "error" not in value, value


async def test_booking_tools_submit_to_evaluator_and_feed_frontdesk(stack, monkeypatch):
    class ScenarioClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat("2026-09-18T10:00:00+02:00").astimezone(tz)

    monkeypatch.setattr(tools, "datetime", ScenarioClock)
    config, agent_url = stack
    call_id = "integration-booking"
    ctx = CallContext(data_dir=config.data_dir, call_id=call_id)
    box = ToolBox(ctx, config)
    box.client = ProsperClient(config)
    box.cache = CatalogueCache()
    result = ToolResult()
    try:
        await box.cache.warm(box.client)
        await box.lookup_patient(result, name="Marta Ruiz Gómez", national_id="12345678Z")
        await box.confirm_patient(result, patient_id="P00042")
        await box.find_availability(
            result, when_phrase="2026-09-21", specialty_name="Medicina general"
        )
        assert ctx.slot_registry
        await box.book_appointment(result, slot_token=next(iter(ctx.slot_registry)))
        async with httpx.AsyncClient(base_url=config.prosper_api_base_url) as clinic:
            response = await clinic.post("/eval/calls", json={"call_id": call_id})
            response.raise_for_status()
            await clinic.post(f"/eval/calls/{call_id}/close")
            ctx.mark_stopped()
            await flush_call(ctx, config)
            await flush_call(ctx, config)
            record = (await clinic.get(f"/eval/calls/{call_id}/record")).json()
        expected = {
            "action": "BOOK", "patient_id": "P00042", "provider_id": "PR01",
            "location_id": "centro", "appointment_type_id": "review",
            "slot": "2026-09-21T09:00:00+02:00", "policy_id": "sanitas",
        }
        assert compare(record["actions"], [[expected]]).passed
        assert len(record["attempts"]) == 1
        async with httpx.AsyncClient(base_url=agent_url) as agent:
            calls = (await agent.get("/ops/api/frontdesk/calls")).json()
            data = (await agent.get("/ops/api/frontdesk/clinic")).json()
        assert calls[0]["diagnostic"]["submissions_succeeded"] == 1
        assert calls[0]["status"] == "ended"
        assert any(p["patient_id"] == "P00042" for p in data["patients"])
        assert data["appointments"][0]["provider_name"]
    finally:
        await box.client.close()
        await box.aclose()


async def test_evaluator_harness_reaches_agent_and_records_silence_fallback(stack):
    config, agent_url = stack
    call_id = "integration-silence"
    async with httpx.AsyncClient(base_url=config.prosper_api_base_url) as clinic:
        await clinic.post("/eval/calls", json={"call_id": call_id})
        evidence = await dial(
            agent_url.replace("http://", "ws://") + "/ws", call_id, [silence(300)],
            after_send_idle_s=0.4, max_call_s=10,
        )
        assert evidence.error is None
        await clinic.post(f"/eval/calls/{call_id}/close")
        for _ in range(100):
            record = (await clinic.get(f"/eval/calls/{call_id}/record")).json()
            if record["actions"]:
                break
            await asyncio.sleep(0.05)
    assert record["actions"] == [{"action": "NO_ACTION", "reason": "out_of_scope"}]
    async with httpx.AsyncClient(base_url=agent_url) as agent:
        calls = (await agent.get("/ops/api/frontdesk/calls")).json()
    assert calls[0]["callId"] == call_id
    assert calls[0]["diagnostic"]["fallback_action_added"] is True


@pytest.mark.parametrize("reason", ["unknown-call", "invalid-body"])
async def test_rejected_submissions_are_failed_in_frontdesk(stack, reason):
    config, agent_url = stack
    ctx = CallContext(data_dir=config.data_dir, call_id=reason)
    ctx.queued_actions = [{"route": "no-action", "reason": "out_of_scope"}]
    if reason == "invalid-body":
        async with httpx.AsyncClient(base_url=config.prosper_api_base_url) as clinic:
            await clinic.post("/eval/calls", json={"call_id": ctx.call_id})
        ctx.queued_actions[0]["reason"] = "not-in-the-contract"
    await flush_call(ctx, config)
    async with httpx.AsyncClient(base_url=agent_url) as agent:
        call = (await agent.get("/ops/api/frontdesk/calls")).json()[0]
    assert call["diagnostic"]["submissions_succeeded"] == 0
    assert call["diagnostic"]["submissions_failed"] == 1
