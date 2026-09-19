"""The submit vocabulary is owned and enforced by the evaluator alone.

This is the always-on half of the agent contract. It pins the routes, the
required fields and the closed reason vocabulary declared in
`evaluator.models` against the receiver in `evaluator.clinic.server`, and it
replays every scenario's accepted outcome through a submit body built by the
evaluator itself.

No module from `backend/` is imported here, so this file always runs in the
evaluator's own virtualenv and can never be skipped silently: vocabulary
drift fails loudly instead of disappearing into a green skip. The opt-in
counterpart, which additionally exercises the agent's own client and payload
builder, lives in `test_agent_main_contract.py`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app
from evaluator.compare import compare
from evaluator.models import OUTCOME_REASONS, ROUTE_FIELDS, ROUTE_TO_VERB, Scenario
from evaluator.runner.experiment import _to_submit_bodies

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "clinic_dataset.json"
SCENARIOS = sorted((ROOT / "scenarios").glob("**/*.yaml"))
KEY = "pk-local-eval"

# One valid body per route. The receiver must accept every route when its
# required fields are present, so these values are the sample the vocabulary
# is checked against; the national id carries a matching check letter on
# purpose, because a wrong one is a separate 422.
VALID_FIELDS: dict[str, dict[str, Any]] = {
    "register": {
        "given_name": "Ana",
        "first_surname": "García",
        "second_surname": "Ruiz",
        "national_id": "45678901G",
        "date_of_birth": "1990-01-12",
        "phone": "655444333",
        "email": "ana.garcia@gmail.com",
        "insurer": "sanitas",
    },
    "book": {
        "patient_id": "P00042",
        "provider_id": "PR01",
        "location_id": "centro",
        "appointment_type_id": "review",
        "slot": "2026-09-21T09:00:00+02:00",
        "policy_id": "sanitas",
    },
    "reschedule": {
        "appointment_id": "A00101",
        "provider_id": "PR01",
        "location_id": "centro",
        "slot": "2026-09-24T16:30:00+02:00",
        "policy_id": "sanitas",
    },
    "cancel": {"appointment_id": "A00101"},
    "no-action": {"reason": "out_of_scope"},
    "escalate": {"reason": "medical_emergency"},
}

MISSING_CASES = [
    (route, field) for route, fields in sorted(ROUTE_FIELDS.items()) for field in fields
]


def _receiver(window_seconds: float = 30.0) -> tuple[httpx.AsyncClient, httpx.ASGITransport]:
    app = create_app(Dataset.load(DATASET), api_key=KEY, window_seconds=window_seconds)
    transport = httpx.ASGITransport(app=app)
    return (
        httpx.AsyncClient(
            transport=transport,
            base_url="http://evaluator.test",
            headers={"X-Api-Key": KEY},
        ),
        transport,
    )


@pytest.fixture
async def receiver():
    client, _ = _receiver()
    async with client as open_client:
        yield open_client


async def _open(client: httpx.AsyncClient, call_id: str) -> str:
    response = await client.post("/eval/calls", json={"call_id": call_id})
    assert response.status_code == 200, response.text
    return call_id


def _flat_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """The record readback nests REGISTER under `new_patient`; submit is flat."""
    nested = fields.get("new_patient")
    return dict(nested) if isinstance(nested, dict) else dict(fields)


def test_valid_samples_cover_every_required_field():
    for route, fields in ROUTE_FIELDS.items():
        assert set(fields) <= set(VALID_FIELDS[route]), f"{route} sample is incomplete"


def test_routes_and_verbs_stay_mutually_consistent():
    assert set(ROUTE_FIELDS) == set(ROUTE_TO_VERB)


@pytest.mark.parametrize("route", sorted(ROUTE_FIELDS))
async def test_each_route_accepts_its_required_fields(receiver, route):
    call_id = await _open(receiver, f"vocabulary-{route}")
    response = await receiver.post(
        f"/api/v1/submit/{route}", json={"call_id": call_id, **VALID_FIELDS[route]}
    )
    assert response.status_code == 200, response.text
    actions = response.json()["record"]["actions"]
    assert [action["action"] for action in actions] == [ROUTE_TO_VERB[route]]


@pytest.mark.parametrize(
    ("route", "field"), MISSING_CASES, ids=[f"{r}-{f}" for r, f in MISSING_CASES]
)
async def test_missing_required_field_is_rejected(receiver, route, field):
    call_id = await _open(receiver, f"missing-{route}-{field}")
    body = {"call_id": call_id, **VALID_FIELDS[route]}
    del body[field]
    response = await receiver.post(f"/api/v1/submit/{route}", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == f"missing fields: {field}"


async def test_empty_required_field_is_rejected_like_a_missing_one(receiver):
    call_id = await _open(receiver, "empty-field")
    response = await receiver.post(
        "/api/v1/submit/cancel", json={"call_id": call_id, "appointment_id": ""}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "missing fields: appointment_id"


@pytest.mark.parametrize("route", ["no-action", "escalate"])
async def test_reason_outside_the_closed_vocabulary_is_rejected(receiver, route):
    call_id = await _open(receiver, f"vocabulary-{route}")
    response = await receiver.post(
        f"/api/v1/submit/{route}", json={"call_id": call_id, "reason": "because-i-said-so"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "reason not in the closed vocabulary"


@pytest.mark.parametrize("reason", sorted(OUTCOME_REASONS))
async def test_every_declared_reason_is_accepted(receiver, reason):
    call_id = await _open(receiver, f"reason-{reason}")
    response = await receiver.post(
        "/api/v1/submit/no-action", json={"call_id": call_id, "reason": reason}
    )
    assert response.status_code == 200, response.text


async def test_reason_is_normalised_before_matching(receiver):
    call_id = await _open(receiver, "reason-normalised")
    response = await receiver.post(
        "/api/v1/submit/no-action", json={"call_id": call_id, "reason": "Out_Of_Scope"}
    )
    assert response.status_code == 200, response.text


async def test_register_rejects_a_wrong_national_id_check_letter(receiver):
    call_id = await _open(receiver, "register-check-letter")
    body = {"call_id": call_id, **VALID_FIELDS["register"], "national_id": "45678901X"}
    response = await receiver.post("/api/v1/submit/register", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == "national_id check letter does not match digits"


async def test_identical_action_is_a_conflict(receiver):
    call_id = await _open(receiver, "duplicate-action")
    body = {"call_id": call_id, **VALID_FIELDS["cancel"]}
    first = await receiver.post("/api/v1/submit/cancel", json=body)
    second = await receiver.post("/api/v1/submit/cancel", json=body)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "identical action already recorded"


async def test_unknown_call_is_not_found(receiver):
    response = await receiver.post(
        "/api/v1/submit/cancel", json={"call_id": "no-such-call", **VALID_FIELDS["cancel"]}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "unknown call_id"


async def test_submission_after_the_window_is_gone():
    client, _ = _receiver(window_seconds=0.01)
    async with client:
        await _open(client, "expired-window")
        await client.post("/eval/calls/expired-window/close")
        await asyncio.sleep(0.05)
        response = await client.post(
            "/api/v1/submit/cancel", json={"call_id": "expired-window", **VALID_FIELDS["cancel"]}
        )
    assert response.status_code == 410
    assert response.json()["detail"] == "submission window closed"


@pytest.mark.parametrize("path", SCENARIOS, ids=[path.stem for path in SCENARIOS])
async def test_scenario_outcomes_are_accepted_and_scored_by_the_receiver(receiver, path):
    scenario = Scenario.load(str(path))
    call_id = await _open(receiver, f"scenario-{scenario.id}")
    for submission in _to_submit_bodies(scenario.accepted_outcomes[0]):
        route = submission["route"]
        response = await receiver.post(
            f"/api/v1/submit/{route}",
            json={"call_id": call_id, **_flat_fields(submission["fields"])},
        )
        assert response.status_code == 200, f"{path.stem} {route}: {response.text}"
    record = (await receiver.get(f"/eval/calls/{call_id}/record")).json()
    assert compare(record["actions"], scenario.accepted_outcomes).passed
