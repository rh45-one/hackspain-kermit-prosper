"""Offline tests for the Prosper API client using httpx.MockTransport."""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from agent.clinic.client import ProsperClient
from agent.clinic.errors import (
    ClinicValidationError,
    NotFoundError,
    ProsperAuthError,
    ProsperError,
    RateLimitedError,
)
from agent.clinic.models import (
    AppointmentsResponse,
    AvailabilityResponse,
    ClinicCatalogue,
    DirectoryResponse,
)
from tests.conftest import load_fixture


class FakeSettings:
    prosper_api_base_url = "https://api.test"
    prosper_api_key = "pk-test-key"


def make_client(handler) -> ProsperClient:
    return ProsperClient(FakeSettings(), transport=httpx.MockTransport(handler))


async def test_sends_x_api_key_header():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key", "")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"status": "ok"})

    client = make_client(handler)
    assert await client.health() == {"status": "ok"}
    assert seen["key"] == "pk-test-key"
    assert seen["path"] == "/api/v1/health"
    await client.close()


async def test_403_raises_auth_error_without_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, json={"detail": "invalid key"})

    client = make_client(handler)
    with pytest.raises(ProsperAuthError):
        await client.list_providers()
    assert calls["n"] == 1  # typed client errors are never retried
    await client.close()


async def test_404_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "unknown"})

    client = make_client(handler)
    with pytest.raises(NotFoundError):
        await client.list_appointments("P99999")
    await client.close()


async def test_422_raises_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "out of calendar"})

    client = make_client(handler)
    with pytest.raises(ClinicValidationError):
        await client.list_specialties()
    await client.close()


async def test_429_raises_rate_limited_without_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"detail": "slow down"})

    client = make_client(handler)
    with pytest.raises(RateLimitedError):
        await client.list_locations()
    assert calls["n"] == 1
    await client.close()


async def test_5xx_retried_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"detail": "unavailable"})
        return httpx.Response(200, json={"specialties": []})

    client = make_client(handler)
    assert await client.list_specialties() == {"specialties": []}
    assert calls["n"] == 2
    await client.close()


async def test_5xx_exhausts_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"detail": "boom"})

    client = make_client(handler)
    with pytest.raises(ProsperError):
        await client.list_locations()
    assert calls["n"] == 3  # initial + 2 retries
    await client.close()


async def test_transport_error_retried_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json={"providers": []})

    client = make_client(handler)
    assert await client.list_providers() == {"providers": []}
    assert calls["n"] == 2
    await client.close()


async def test_directory_returns_typed_matches():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/directory"
        assert request.url.params["name"] == "Marta Ruiz Gomez"
        assert request.url.params["date_of_birth"] == "1988-03-14"
        return httpx.Response(200, json=load_fixture("directory"))

    client = make_client(handler)
    result = await client.search_directory(name="Marta Ruiz Gomez", date_of_birth="1988-03-14")
    assert isinstance(result, DirectoryResponse)
    assert [m.patient_id for m in result.matches] == ["P00042", "P00043"]
    await client.close()


async def test_directory_omits_unset_params():
    def handler(request: httpx.Request) -> httpx.Response:
        assert set(request.url.params.keys()) == {"name"}
        return httpx.Response(200, json={"matches": []})

    client = make_client(handler)
    result = await client.search_directory(name="ana")
    assert result.matches == []
    await client.close()


async def test_appointments_typed_and_when_validated():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/patients/P00042/appointments"
        assert request.url.params["when"] == "past"
        return httpx.Response(200, json=load_fixture("appointments"))

    client = make_client(handler)
    result = await client.list_appointments("P00042", when="past")
    assert isinstance(result, AppointmentsResponse)
    assert result.appointments[0].appointment_id == "A00101"
    with pytest.raises(ClinicValidationError):
        await client.list_appointments("P00042", when="tomorrow")
    await client.close()


async def test_availability_repeats_insurer_param():
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["insurer"] = request.url.params.get_list("insurer")
        seen["date_from"] = request.url.params["date_from"]
        seen["date_to"] = request.url.params["date_to"]
        seen["patient_id"] = request.url.params.get("patient_id")
        return httpx.Response(200, json=load_fixture("availability"))

    client = make_client(handler)
    result = await client.search_availability(
        date_from=date(2026, 9, 21),
        date_to=date(2026, 9, 25),
        specialty_id="general",
        patient_id="P00042",
        insurer=["sanitas", "asisa"],
    )
    assert seen["insurer"] == ["sanitas", "asisa"]  # repeated on the wire
    assert seen["date_from"] == "2026-09-21"
    assert seen["date_to"] == "2026-09-25"
    assert seen["patient_id"] == "P00042"
    assert isinstance(result, AvailabilityResponse)
    assert result.appointment_type.id == "review"
    assert [b.model_dump() for b in result.blocked] == [
        {"provider_id": "PR02", "restriction": "r-referral-derm"}
    ]
    await client.close()


async def test_availability_accepts_single_insurer_string():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get_list("insurer") == ["sanitas"]
        return httpx.Response(200, json=load_fixture("availability"))

    client = make_client(handler)
    result = await client.search_availability(date(2026, 9, 21), date(2026, 9, 21), insurer="sanitas")
    assert len(result.slots) == 3
    await client.close()


async def test_get_clinic_returns_catalogue_model():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/clinic"
        return httpx.Response(200, json=load_fixture("clinic"))

    client = make_client(handler)
    catalogue = await client.get_clinic()
    assert isinstance(catalogue, ClinicCatalogue)
    assert catalogue.clinic_name == "Clínica Arenal"
    assert catalogue.calendar.closure_days == ["2026-10-12"]
    await client.close()
