from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app
from evaluator.compare import compare
from evaluator.models import Scenario
from evaluator.runner.experiment import _to_submit_bodies

agent_client = pytest.importorskip(
    "agent.clinic.client", reason="Opt-in contract check: expose the main agent via PYTHONPATH"
)
agent_recorder = pytest.importorskip("agent.scheduling.recorder")

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = sorted((ROOT / "scenarios").glob("**/*.yaml"))
KEY = "pk-local-eval"


@pytest.fixture
async def rig():
    app = create_app(Dataset.load(ROOT / "data" / "clinic_dataset.json"), api_key=KEY)
    transport = httpx.ASGITransport(app=app)
    settings = SimpleNamespace(prosper_api_base_url="http://evaluator.test", prosper_api_key=KEY)
    client = agent_client.ProsperClient(settings, transport=transport)
    async with httpx.AsyncClient(
        transport=transport, base_url=settings.prosper_api_base_url, headers={"X-Api-Key": KEY}
    ) as receiver:
        try:
            yield client, receiver
        finally:
            await client.close()


async def test_main_client_reads_local_catalogue(rig):
    client, _ = rig
    assert await client.health()
    catalogue = await client.get_clinic()
    assert catalogue.providers
    assert catalogue.locations
    assert catalogue.appointment_types


async def test_main_client_identifies_patient_and_reads_appointments(rig):
    client, _ = rig
    directory = await client.search_directory(national_id="12345678Z")
    assert [patient.patient_id for patient in directory.matches] == ["P00042"]
    appointments = await client.list_appointments("P00042", when="all")
    assert appointments.appointments
    assert all(appointment.patient_id == "P00042" for appointment in appointments.appointments)


async def test_main_client_reads_local_slots_and_their_types(rig):
    client, _ = rig
    result = await client.search_availability(
        date(2026, 9, 21), date(2026, 9, 21),
        specialty_id="general", patient_id="P00042", insurer=["sanitas"],
    )
    assert result.appointment_type.id == "review"
    assert result.slots
    assert all(slot.appointment_type_id == result.appointment_type.id for slot in result.slots)
    assert all("sanitas" in slot.payable_with for slot in result.slots)


@pytest.mark.parametrize("path", SCENARIOS, ids=[path.stem for path in SCENARIOS])
async def test_main_recorder_payloads_are_accepted_and_scored_locally(rig, path):
    _, receiver = rig
    scenario = Scenario.load(str(path))
    call_id = f"contract-{scenario.id}"
    response = await receiver.post("/eval/calls", json={"call_id": call_id})
    assert response.status_code == 200
    for submission in _to_submit_bodies(scenario.accepted_outcomes[0]):
        route = submission["route"]
        body = agent_recorder.build_body({"route": route, **submission["fields"]}, call_id)
        response = await receiver.post(f"/api/v1/submit/{route}", json=body)
        assert response.status_code == 200, response.text
    record = (await receiver.get(f"/eval/calls/{call_id}/record")).json()
    assert compare(record["actions"], scenario.accepted_outcomes).passed
