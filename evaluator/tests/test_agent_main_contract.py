import importlib
import importlib.util
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

AGENT_ABSENT_REASON = "Opt-in contract check: expose the main agent via PYTHONPATH=backend/src"


def _load_agent_modules():
    """Import the agent's own modules, or state plainly why that is impossible.

    `pytest.importorskip` also swallows a missing third-party dependency of
    `agent.*`, so a broken checkout could report a green skip and hide real
    drift. Absent source is a deliberate opt-in skip; source that is present
    but not importable is a collection failure instead.
    """
    try:
        present = importlib.util.find_spec("agent") is not None
    except (ImportError, ValueError):  # a broken parent package is not a skip
        present = False
    if not present:
        pytest.skip(AGENT_ABSENT_REASON, allow_module_level=True)
    try:
        return (
            importlib.import_module("agent.clinic.client"),
            importlib.import_module("agent.scheduling.recorder"),
        )
    except ImportError as exc:
        pytest.fail(f"agent source is on the path but not importable: {exc}", pytrace=False)


agent_client, agent_recorder = _load_agent_modules()

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
