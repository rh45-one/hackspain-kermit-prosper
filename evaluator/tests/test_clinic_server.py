"""Local clinic server: contract status codes + read API over the dataset."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import CallRegistry, create_app

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"
KEY = "pk-local-eval"
AUTH = {"X-Api-Key": KEY}

BOOK_BODY = {
    "call_id": "c1",
    "patient_id": "P00042",
    "provider_id": "PR01",
    "location_id": "centro",
    "appointment_type_id": "review",
    "slot": "2026-09-21T09:00:00+02:00",
    "policy_id": "sanitas",
}
REGISTER_BODY = {
    "call_id": "c1",
    "given_name": "Marta",
    "first_surname": "Ruiz",
    "second_surname": "Gómez",
    "national_id": "12345678Z",
    "date_of_birth": "1988-03-14",
    "phone": "612345678",
    "email": "marta@example.com",
    "insurer": "sanitas",
}


@pytest.fixture
def dataset() -> Dataset:
    return Dataset.load(DATASET)


@pytest.fixture
async def client(dataset):
    app = create_app(dataset, api_key=KEY)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


class TestRegistry:
    def test_unknown_call_404(self):
        reg = CallRegistry()
        status, _ = reg.submit("nope", "book", BOOK_BODY)
        assert status == 404

    def test_open_call_accepts(self):
        reg = CallRegistry()
        reg.open("c1")
        status, payload = reg.submit("c1", "book", BOOK_BODY)
        assert status == 200
        assert payload["record"]["actions"][0]["action"] == "BOOK"

    def test_closed_within_window_accepts(self):
        reg = CallRegistry(window_seconds=60)
        reg.open("c1")
        reg.close("c1")
        status, _ = reg.submit("c1", "book", BOOK_BODY)
        assert status == 200

    def test_past_window_410(self):
        reg = CallRegistry(window_seconds=0)
        reg.open("c1")
        reg.close("c1")
        status, _ = reg.submit("c1", "book", BOOK_BODY)
        assert status == 410

    def test_identical_retry_409(self):
        reg = CallRegistry()
        reg.open("c1")
        assert reg.submit("c1", "book", BOOK_BODY)[0] == 200
        assert reg.submit("c1", "book", dict(BOOK_BODY))[0] == 409

    def test_missing_field_422(self):
        reg = CallRegistry()
        reg.open("c1")
        body = {k: v for k, v in BOOK_BODY.items() if k != "slot"}
        status, _ = reg.submit("c1", "book", body)
        assert status == 422

    def test_bad_check_letter_422(self):
        reg = CallRegistry()
        reg.open("c1")
        body = {**REGISTER_BODY, "national_id": "12345678A"}
        status, _ = reg.submit("c1", "register", body)
        assert status == 422

    def test_bad_reason_422(self):
        reg = CallRegistry()
        reg.open("c1")
        status, _ = reg.submit("c1", "no-action", {"call_id": "c1", "reason": "made up"})
        assert status == 422

    def test_register_records_nested_shape(self):
        reg = CallRegistry()
        reg.open("c1")
        reg.submit("c1", "register", REGISTER_BODY)
        action = reg.record("c1")[0]
        assert action["action"] == "REGISTER"
        assert action["new_patient"]["national_id"] == "12345678Z"


class TestHttp:
    async def test_health_no_auth(self, client):
        assert (await client.get("/api/v1/health")).status_code == 200

    async def test_auth_required(self, client):
        assert (await client.get("/api/v1/directory")).status_code == 403

    async def test_submit_unknown_call_404(self, client):
        resp = await client.post("/api/v1/submit/book", json=BOOK_BODY, headers=AUTH)
        assert resp.status_code == 404

    async def test_submit_roundtrip(self, client):
        await client.post("/eval/calls", json={"call_id": "c1"})
        resp = await client.post("/api/v1/submit/book", json=BOOK_BODY, headers=AUTH)
        assert resp.status_code == 200
        record = await client.get("/eval/calls/c1/record")
        assert record.json()["actions"][0]["action"] == "BOOK"

    async def test_submit_malformed_422(self, client):
        await client.post("/eval/calls", json={"call_id": "c1"})
        resp = await client.post("/api/v1/submit/book", json={"call_id": "c1"}, headers=AUTH)
        assert resp.status_code == 422

    async def test_submit_missing_call_id_422(self, client):
        resp = await client.post("/api/v1/submit/book", json={"foo": 1}, headers=AUTH)
        assert resp.status_code == 422

    async def test_directory_by_national_id(self, client, dataset):
        resp = await client.get(
            "/api/v1/directory", params={"national_id": "12345678-Z"}, headers=AUTH
        )
        matches = resp.json()["matches"]
        assert [m["patient_id"] for m in matches] == ["P00042"]

    async def test_availability_slots(self, client):
        resp = await client.get(
            "/api/v1/availability",
            params={
                "date_from": "2026-09-21",
                "date_to": "2026-09-21",
                "provider_id": "PR01",
                "location_id": "centro",
            },
            headers=AUTH,
        )
        slots = resp.json()["slots"]
        starts = {s["start_time"] for s in slots}
        # booked_slots cover 09:15 and 09:30 - 09:00 is the first free one.
        assert "2026-09-21T09:00:00+02:00" in starts
        assert "2026-09-21T09:15:00+02:00" not in starts

    async def test_availability_outside_calendar_422(self, client):
        resp = await client.get(
            "/api/v1/availability",
            params={"date_from": "2027-01-01", "date_to": "2027-01-02"},
            headers=AUTH,
        )
        assert resp.status_code == 422

    async def test_availability_blocked_leave(self, client):
        # PR02 is on leave 2026-09-14..30.
        resp = await client.get(
            "/api/v1/availability",
            params={
                "date_from": "2026-09-21",
                "date_to": "2026-09-21",
                "provider_id": "PR02",
            },
            headers=AUTH,
        )
        body = resp.json()
        assert body["slots"] == []
        assert body["blocked"][0]["restriction"] == "provider_on_leave"

    async def test_eval_record_unknown_404(self, client):
        assert (await client.get("/eval/calls/nope/record")).status_code == 404
