"""Offline guard tests for the LLM tool layer.

The model converses, the tools decide. These tests prove the guards: invented
ids are structurally impossible, identity is gated, protected fields never
reach tool output, and results are deterministic.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from agent.brain.tools import ToolBox
from agent.clinic.cache import CatalogueCache
from agent.clinic.models import (
    AppointmentsResponse,
    AvailabilityResponse,
    DirectoryResponse,
)
from agent.scheduling.dates import MadridDateResolver
from agent.voice.context import CallContext
from tests.conftest import load_fixture

MADRID = ZoneInfo("Europe/Madrid")


class FakeParams:
    """Stands in for pipecat's FunctionCallParams: captures the tool result."""

    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    async def result_callback(self, result: dict[str, Any]) -> None:
        self.results.append(result)

    @property
    def result(self) -> dict[str, Any]:
        assert self.results, "tool never called result_callback"
        return self.results[-1]


class FakeClinicClient:
    """Scripted clinic client returning typed models, recording availability calls."""

    def __init__(self) -> None:
        self.availability_calls: list[dict[str, Any]] = []

    async def search_directory(self, **kwargs: Any) -> DirectoryResponse:
        return DirectoryResponse.model_validate(load_fixture("directory"))

    async def list_appointments(self, patient_id: str, when: str = "upcoming") -> AppointmentsResponse:
        return AppointmentsResponse.model_validate(load_fixture("appointments"))

    async def search_availability(self, **kwargs: Any) -> AvailabilityResponse:
        self.availability_calls.append(kwargs)
        return AvailabilityResponse.model_validate(load_fixture("availability"))


class FakeSettings:
    prosper_api_base_url = "https://api.test"
    prosper_api_key = "pk-test"
    data_dir = "./data"


@pytest.fixture
async def cache() -> CatalogueCache:
    class _Client:
        async def get_clinic(self) -> dict:
            return load_fixture("clinic")

    cache = CatalogueCache()
    await cache.warm(_Client())
    return cache


@pytest.fixture
def ctx(tmp_path) -> CallContext:
    return CallContext(data_dir=str(tmp_path / "data"), call_id="test-call-1")


@pytest.fixture
def box(ctx, cache) -> ToolBox:
    toolbox = ToolBox(ctx, FakeSettings())
    toolbox.client = FakeClinicClient()
    toolbox.cache = cache
    toolbox.resolver = MadridDateResolver()
    return toolbox


async def confirm_marta(box: ToolBox, params: FakeParams | None = None) -> FakeParams:
    """Drive lookup + confirm to reach the identified state."""
    params = params or FakeParams()
    await box.lookup_patient(params, name="Marta Ruiz Gómez", date_of_birth="1988-03-14")
    await box.confirm_patient(params, patient_id="P00042")
    return params


# ---- identity guards ------------------------------------------------------
async def test_book_requires_confirmed_patient(box):
    params = FakeParams()
    await box.book_appointment(params, slot_token="s1")
    assert "error" in params.result


async def test_cancel_requires_confirmed_patient(box):
    params = FakeParams()
    await box.cancel_appointment(params, appointment_id="A00101")
    assert "error" in params.result


async def test_confirm_rejects_invented_patient_id(box):
    params = FakeParams()
    await box.lookup_patient(params, name="Marta Ruiz Gómez", date_of_birth="1988-03-14")
    await box.confirm_patient(params, patient_id="P99999")
    assert "error" in params.result
    assert box.ctx.confirmed_patient is None


async def test_confirm_accepts_only_lookup_results(box):
    params = FakeParams()
    await box.lookup_patient(params, name="Marta Ruiz Gómez", date_of_birth="1988-03-14")
    await box.confirm_patient(params, patient_id="P00042")
    assert params.result == {"confirmed": True, "note": box.ctx.confirmed_patient["note"]}
    assert box.ctx.confirmed_patient["patient_id"] == "P00042"


async def test_candidates_store_no_protected_fields(box, ctx):
    params = FakeParams()
    await box.lookup_patient(params, name="Marta Ruiz Gómez", date_of_birth="1988-03-14")
    for candidate in ctx.patient_candidates:
        assert "national_id" not in candidate
        assert "phone" not in candidate


async def test_no_protected_fields_in_any_tool_result(box):
    params = FakeParams()
    await box.lookup_patient(params, name="Marta Ruiz Gómez", date_of_birth="1988-03-14")
    await box.confirm_patient(params, patient_id="P00042")
    await box.list_my_appointments(params)
    await box.find_availability(params, when_phrase="tomorrow")
    for payload in params.results:
        blob = str(payload)
        assert "12345678Z" not in blob
        assert "612345678" not in blob
        assert "600111222" not in blob


# ---- registry guards ------------------------------------------------------
async def test_book_rejects_unknown_slot_token(box):
    params = await confirm_marta(box)
    await box.book_appointment(params, slot_token="s1")
    assert "unknown slot_token" in params.result["error"]
    assert box.ctx.queued_actions == []


async def test_book_accepts_only_registered_slots(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow")
    token = params.result["slots"][0]["token"]
    await box.book_appointment(params, slot_token=token)
    action = box.ctx.queued_actions[-1]
    assert action["route"] == "book"
    assert action["patient_id"] == "P00042"
    assert action["appointment_type_id"] == "review"  # server-selected type
    assert action["policy_id"] == "sanitas"  # patient's plan on file
    # The token is the only handle the model has; real values stay in ctx.
    assert token in box.ctx.slot_registry


async def test_cancel_rejects_invented_appointment_id(box):
    params = await confirm_marta(box)
    await box.cancel_appointment(params, appointment_id="A-INVENTED")
    assert "unknown appointment_id" in params.result["error"]
    assert box.ctx.queued_actions == []


async def test_cancel_accepts_only_listed_appointments(box):
    params = await confirm_marta(box)
    await box.list_my_appointments(params)
    await box.cancel_appointment(params, appointment_id="A00101")
    action = box.ctx.queued_actions[-1]
    assert action == {"route": "cancel", "appointment_id": "A00101"}


async def test_reschedule_requires_both_registries(box):
    params = await confirm_marta(box)
    await box.reschedule_appointment(params, appointment_id="A00101", slot_token="s1")
    assert "error" in params.result
    await box.list_my_appointments(params)
    await box.reschedule_appointment(params, appointment_id="A00101", slot_token="s1")
    assert "error" in params.result  # still no slot registered
    await box.find_availability(params, when_phrase="tomorrow")
    token = params.result["slots"][0]["token"]
    await box.reschedule_appointment(params, appointment_id="A00101", slot_token=token)
    action = box.ctx.queued_actions[-1]
    assert action["route"] == "reschedule"
    assert action["appointment_id"] == "A00101"


async def test_slot_registries_are_per_call_context(tmp_path, cache):
    """A token from one call's context is worthless in another."""
    ctx_a = CallContext(data_dir=str(tmp_path / "a"), call_id="call-a")
    ctx_b = CallContext(data_dir=str(tmp_path / "b"), call_id="call-b")
    labelled_a = ctx_a.register_slots([{"provider_id": "PR01", "start_time": "x"}])
    assert ctx_b.slot_registry.get(labelled_a[0]["token"]) is None


# ---- availability behaviour ----------------------------------------------
async def test_availability_passes_patient_id(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow")
    call = box.client.availability_calls[-1]
    assert call["patient_id"] == "P00042"


async def test_availability_server_selects_appointment_type(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow")
    assert params.result["suggested_appointment_type"]["id"] == "review"


async def test_blocked_restrictions_preserved_exactly(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow")
    assert params.result["blocked_reasons"] == [
        {"provider_id": "PR02", "restriction": "r-referral-derm"}
    ]


async def test_unresolved_phrase_searches_from_tomorrow(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="cuando sea")
    call = box.client.availability_calls[-1]
    tomorrow = datetime.now(MADRID).date() + timedelta(days=1)
    assert call["date_from"] == tomorrow
    assert (call["date_to"] - call["date_from"]).days == 13  # 14-day API limit


async def test_resolved_phrase_targets_one_day(box):
    params = await confirm_marta(box)
    tomorrow = datetime.now(MADRID).date() + timedelta(days=1)
    await box.find_availability(params, when_phrase="tomorrow")
    call = box.client.availability_calls[-1]
    assert call["date_from"] == call["date_to"] == tomorrow


async def test_part_of_day_filter(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", part_of_day="morning")
    starts = [slot["start_time"] for slot in params.result["slots"]]
    # Both morning slots (before 14:00), the 16:00 one is gone.
    assert starts == ["2026-09-21T09:30:00+02:00", "2026-09-22T10:00:00+02:00"]


async def test_language_filter(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", language="catalán")
    providers = {slot["provider_id"] for slot in params.result["slots"]}
    assert providers == {"PR01"}  # PR02 speaks no Catalan; PR03 has no slots here


async def test_provider_lookup_is_accent_insensitive(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", provider_name="saez")
    call = box.client.availability_calls[-1]
    assert call["provider_id"] == "PR01"


async def test_unknown_provider_or_specialty_is_an_error(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", provider_name="Dr. Nadie")
    assert "no provider named" in params.result["error"]
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="astrología")
    assert "no specialty named" in params.result["error"]
    assert box.client.availability_calls == []  # never queried the API


async def test_slot_results_are_deterministic(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow")
    first = params.result["slots"]
    await box.find_availability(params, when_phrase="tomorrow")
    second = params.result["slots"]
    # Same query, same order: earliest slot first, provider id as tie-break.
    assert [s["start_time"] for s in first] == [s["start_time"] for s in second]
    starts = [s["start_time"] for s in first]
    assert starts == sorted(starts)


# ---- registration and refusal --------------------------------------------
async def test_register_rejects_bad_check_letter(box, ctx):
    params = FakeParams()
    await box.register_new_patient(
        params,
        given_name="Ana",
        first_surname="García",
        second_surname="López",
        national_id="12345678K",  # letter does not match
        date_of_birth="1990-01-01",
        phone="611222333",
        email="ana dot garcia at gmail dot com",
        insurer="sanitas",
    )
    assert "check letter" in params.result["error"]
    assert ctx.queued_actions == []


async def test_register_normalizes_and_queues(box, ctx):
    params = FakeParams()
    await box.register_new_patient(
        params,
        given_name="Ana",
        first_surname="García",
        second_surname="López",
        national_id="1234 5678-Z",
        date_of_birth="1990-01-01",
        phone="611222333",
        email="ana.garcia@gmail.com",
        insurer="Sanitas",
    )
    action = ctx.queued_actions[-1]
    assert action["route"] == "register"
    assert action["national_id"] == "12345678Z"


async def test_finish_requires_closed_vocabulary_reason(box, ctx):
    params = FakeParams()
    await box.finish_without_booking(params, reason="because_i_said_so")
    assert "not allowed" in params.result["error"]
    assert "out_of_scope" in params.result["allowed"]
    assert ctx.queued_actions == []


async def test_finish_queues_refusal(box, ctx):
    params = FakeParams()
    await box.finish_without_booking(params, reason="No_Availability")
    assert ctx.queued_actions[-1] == {"route": "no-action", "reason": "no_availability"}


async def test_finish_does_not_override_a_queued_action(box, ctx):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow")
    token = params.result["slots"][0]["token"]
    await box.book_appointment(params, slot_token=token)
    await box.finish_without_booking(params, reason="out_of_scope")
    assert params.result["noted"] is False
    assert ctx.queued_actions[-1]["route"] == "book"  # booking stands


async def test_escalate_queues_action(box, ctx):
    params = FakeParams()
    await box.escalate_call(params, reason="medical_emergency")
    assert ctx.queued_actions[-1] == {"route": "escalate", "reason": "medical_emergency"}


async def test_escalate_rejects_unknown_reason(box, ctx):
    params = FakeParams()
    await box.escalate_call(params, reason="just_because")
    assert "error" in params.result
    assert ctx.queued_actions == []


# ---- clinic failures surface as results, never as crashes ------------------
async def test_clinic_failure_returns_error_result(box):
    class FailingClient:
        async def search_directory(self, **kwargs: Any) -> Any:
            raise TimeoutError("api down")

    box.client = FailingClient()
    params = FakeParams()
    await box.lookup_patient(params, name="Marta", date_of_birth="1988-03-14")
    assert "lookup_patient failed" in params.result["error"]


# ---- unused-date helper sanity ---------------------------------------------
async def test_date_object_serialization(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow")
    call = box.client.availability_calls[-1]
    assert isinstance(call["date_from"], date)
