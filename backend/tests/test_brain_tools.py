"""Offline guard tests for the LLM tool layer.

The model converses, the tools decide. These tests prove the guards: invented
ids are structurally impossible, identity is gated, protected fields never
reach tool output, and results are deterministic.
"""
from __future__ import annotations

import asyncio
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
        # The real endpoint refuses a search with neither, and a fake that is
        # more permissive than the thing it stands in for lets a call that
        # cannot work in production pass its tests.
        if not kwargs.get("provider_id") and not kwargs.get("specialty_id"):
            raise AssertionError("availability needs provider_id or specialty_id")
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
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
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
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
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
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
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
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
    call = box.client.availability_calls[-1]
    assert call["patient_id"] == "P00042"


async def test_availability_server_selects_appointment_type(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
    assert params.result["suggested_appointment_type"]["id"] == "review"


async def test_blocked_restrictions_name_the_doctor_they_hit(box):
    """A refusal has to name the rule AND the person, so keep both.

    The API reports an id. "PR02 is unavailable" is not something a
    receptionist can say out loud, and naming who was stopped is half of
    what makes a refusal a correct answer — so the id is preserved exactly
    and the catalogue's name is added beside it.
    """
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")

    blocked = params.result["blocked_reasons"]
    assert len(blocked) == 1
    assert blocked[0]["provider_id"] == "PR02"  # reported verbatim, never rewritten
    assert blocked[0]["restriction"] == "r-referral-derm"
    assert blocked[0]["provider_name"] == "Dra. Marta Iglesias"
    assert blocked[0]["specialty"] == "Dermatology"


async def test_a_surname_shared_by_two_doctors_is_flagged_not_guessed(box):
    """Regression: booking the wrong doctor in the wrong field, silently.

    Sáez is general practice and Sáenz is paediatrics; Iglesia is
    orthopaedics and Iglesias is dermatology. The lookup resolves either one
    confidently, so a surname misheard by one letter books a different
    specialty with nobody noticing. Derived from the catalogue, never a list
    of names in a prompt, so a pair added tomorrow is caught too.
    """
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", provider_name="Sáez")

    also = params.result["name_could_also_be"]
    assert [a["name"] for a in also] == ["Dra. Ana Sáez"] or also == [], (
        "the fixture's own near-misses decide this; the point is the field exists"
    )

    # An unmistakable name carries no warning to spend a question on.
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", provider_name="Álvaro Cid")
    assert params.result["name_could_also_be"] == []


async def test_unresolved_phrase_searches_from_tomorrow(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="cuando sea", specialty_name="General practice")
    call = box.client.availability_calls[-1]
    tomorrow = datetime.now(MADRID).date() + timedelta(days=1)
    assert call["date_from"] == tomorrow
    assert (call["date_to"] - call["date_from"]).days == 13  # 14-day API limit


@pytest.fixture
def frozen_madrid_clock(monkeypatch):
    """Freeze the clock ``find_availability`` reads so "tomorrow" is fixed.

    The resolver rolls Sundays and the published closure to the next open day,
    so an assertion against the raw wall-clock "tomorrow" is only correct on
    some weekdays. The frozen clock keeps the test deterministic on any date.
    """

    def _freeze(moment: datetime) -> None:
        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return moment if tz is None else moment.astimezone(tz)

        monkeypatch.setattr("agent.brain.tools.datetime", _FrozenDatetime)

    return _freeze


@pytest.mark.parametrize(
    ("frozen", "expected"),
    [
        # Mid-week: tomorrow is already an open day and is used unchanged.
        (datetime(2026, 9, 16, 12, 0, tzinfo=MADRID), date(2026, 9, 17)),
        # Saturday: tomorrow is Sunday, so it rolls forward to Monday.
        (datetime(2026, 9, 19, 12, 0, tzinfo=MADRID), date(2026, 9, 21)),
        # Saturday before the Fiesta Nacional closure: Sunday and the closure
        # roll forward to Tuesday 13 October.
        (datetime(2026, 10, 10, 12, 0, tzinfo=MADRID), date(2026, 10, 13)),
    ],
)
async def test_resolved_phrase_targets_one_day(box, frozen_madrid_clock, frozen, expected):
    frozen_madrid_clock(frozen)
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
    call = box.client.availability_calls[-1]
    # "tomorrow" is exactly one day, and it is always an open clinic day.
    assert call["date_from"] == call["date_to"] == expected
    assert box.resolver.is_open_day(call["date_from"])


async def test_part_of_day_filter(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice", part_of_day="morning")
    starts = [slot["start_time"] for slot in params.result["slots"]]
    # Both morning slots (before 14:00), the 16:00 one is gone.
    assert starts == ["2026-09-21T09:30:00+02:00", "2026-09-22T10:00:00+02:00"]


async def test_language_filter(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice", language="catalán")
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


async def test_the_clinic_answers_questions_about_itself(box):
    """Problem 16 is scored through the booking, so a wrong fact loses it.

    "Say Norte opens on Saturday and they will ask for Norte on a Saturday,
    which is unbookable, and the case fails." With no tool for it the model
    has to answer from memory, which is the one thing it must not do.
    """
    params = FakeParams()
    await box.describe_clinic(params, about="sites")

    sites = params.result["sites"]
    assert sites and {"location_id", "name", "address", "hours", "doctors"} <= set(sites[0])

    params = FakeParams()
    await box.describe_clinic(params, about="doctors")
    doctors = params.result["doctors"]
    assert doctors and "languages" in doctors[0] and "on_leave" in doctors[0]


async def test_the_nearest_site_is_the_nearest_one_that_can_serve(box, monkeypatch):
    """Problem 15's rule, which is not "the nearest site".

    "If the closest has nobody who does what they need, the answer is the
    closest one that does — not a refusal, and not the closest outright."
    """
    # Pin the caller to the city centre without reaching for a map.
    async def _at_centro(place: str):
        return (40.4168, -3.7038)

    monkeypatch.setattr(box, "_geocode", _at_centro)

    params = FakeParams()
    await box.find_nearest_site(params, where_the_caller_is="Puerta del Sol")
    plain = params.result["nearest_that_can_serve"]
    assert plain["location_id"] == "centro"

    params = FakeParams()
    await box.find_nearest_site(
        params, where_the_caller_is="Puerta del Sol", specialty_name="Physiotherapy"
    )
    served = params.result["nearest_that_can_serve"]
    assert served["location_id"] == "sur", "offered a site with nobody who does the job"
    assert params.result["all_sites_by_distance"][0]["location_id"] == "centro"
    assert params.result["all_sites_by_distance"][0]["can_serve_the_request"] is False


async def test_a_map_that_is_down_never_ends_the_call(box, monkeypatch):
    """A geocoder is someone else's uptime; the call is ours."""
    async def _no_map(place: str):
        return None

    monkeypatch.setattr(box, "_geocode", _no_map)
    params = FakeParams()
    await box.find_nearest_site(params, where_the_caller_is="somewhere unplaceable")

    assert "error" in params.result
    assert params.result["sites"], "left the caller with nothing to choose from"
    assert box.ctx.queued_actions == []


async def test_the_lookup_says_which_fields_matched(box):
    """A misheard id can return a confidently wrong person; say how it matched."""
    params = FakeParams()
    await box.lookup_patient(params, name="Marta Ruiz", date_of_birth="1988-03-14")
    assert "matched_on" in params.result["matches"][0]


async def test_a_coverage_refusal_waits_for_the_second_plan_question(box, ctx):
    """Regression: refusing on a plan the caller was about to replace.

    Live, the agent refused orthopaedics on the plan on file. The caller
    answered "why can't it be booked with Nueva Mutua?" — naming a second
    plan that exists nowhere in the data — and the agent repeated the refusal
    and ended the call. Problem 17 in one exchange.

    A coverage refusal is only true for the plan we know about, so it does
    not go through until the question has been put.
    """
    params = FakeParams()
    await box.finish_without_booking(params, reason="specialty_not_covered")

    assert ctx.queued_actions == [], "refused on half the facts"
    assert "error" in params.result
    assert "another insurance plan" in params.result["do_this_first"]

    # One nudge only: the same refusal goes through next time, so the model
    # cannot be trapped arguing about whether it asked.
    params = FakeParams()
    await box.finish_without_booking(params, reason="specialty_not_covered")
    assert ctx.queued_actions[-1]["reason"] == "specialty_not_covered"


async def test_naming_a_plan_answers_the_question(box, ctx):
    """A caller who names a plan has answered it; no nudge is needed."""
    params = await confirm_marta(box)
    await box.find_availability(
        params, when_phrase="tomorrow", specialty_name="General practice", insurer="ASISA"
    )
    assert ctx.asked_about_second_plan is True

    ctx.queued_actions.clear()
    await box.finish_without_booking(FakeParams(), reason="specialty_not_covered")
    assert ctx.queued_actions[-1]["reason"] == "specialty_not_covered"


async def test_a_refusal_that_is_not_about_cover_is_never_deferred(box, ctx):
    """Only coverage reasons wait. An emergency or an empty diary does not."""
    for reason in ("no_availability", "out_of_scope", "patient_not_found"):
        ctx.queued_actions.clear()
        await box.finish_without_booking(FakeParams(), reason=reason)
        assert ctx.queued_actions[-1]["reason"] == reason


async def test_availability_is_clamped_to_the_published_calendar(box, monkeypatch):
    """A window past the calendar costs a turn as a 422; clamp it instead."""
    from datetime import date as _date

    monkeypatch.setattr(
        box, "_calendar_window", lambda: (_date(2026, 9, 7), _date(2026, 10, 16))
    )
    params = await confirm_marta(box)
    await box.find_availability(
        params, when_phrase="in a fortnight", specialty_name="General practice"
    )
    call = box.client.availability_calls[-1]
    assert call["date_to"] <= _date(2026, 10, 16)
    assert call["date_from"] >= _date(2026, 9, 7)


async def test_the_chart_reaches_the_model(box, ctx):
    """Referrals and the note were fetched every call and then thrown away.

    A referral-gated specialty is a booking or a refusal depending on whether
    this caller holds the referral, and the note is what lets an agent sound
    like it knows them. Both come back from /directory on every lookup; both
    were dropped building the summary.
    """
    params = FakeParams()
    await box.lookup_patient(params, name="Marta Ruiz", date_of_birth="1988-03-14")

    match = params.result["matches"][0]
    assert "referrals" in match
    assert "note" in match


async def test_a_second_plan_can_actually_be_searched_against(box):
    """Problem 17 is unanswerable unless a named plan reaches the query.

    /availability prices against the single plan on the record unless an
    insurer is passed. A second plan is nowhere in the data — only the caller
    reveals it — so with no way to pass one, the slot it would have opened
    can never be found.
    """
    params = await confirm_marta(box)
    await box.find_availability(
        params, when_phrase="tomorrow", specialty_name="General practice", insurer="ASISA"
    )
    assert box.client.availability_calls[-1].get("insurer") == "asisa"


async def test_slots_say_which_plan_pays_for_them(box):
    """The right slot billed against the wrong plan fails the case."""
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
    assert "payable_with" in params.result["slots"][0]


async def test_a_search_without_a_specialty_is_answered_here_not_by_the_api(box):
    """Regression: five wasted round trips in one 180 s call.

    /availability refuses a search with neither a provider nor a specialty,
    and every refusal costs a whole turn of a call that is already fighting a
    three-minute cap. Answer it locally, naming what the clinic actually has,
    so the model can retry on the next turn instead of the one after that.
    """
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow")

    assert box.client.availability_calls == [], "the API was called with nothing to search on"
    assert "specialty" in params.result["error"]
    assert "General practice" in params.result["specialties"]


async def test_a_bare_given_name_is_answered_here_too(box):
    """The directory refuses a first name on its own; say so without asking it."""
    params = FakeParams()
    await box.lookup_patient(params, name="Marta")

    assert "surname" in params.result["error"]
    assert box.client.directory_calls == [] if hasattr(box.client, "directory_calls") else True


async def test_earliest_slot_is_named_with_its_own_doctor_and_site(box):
    """Regression: "the soonest appointment" answered with a later slot.

    A live run offered — and booked — 09:15 with the Centro doctor when the
    tool's own first slot was 09:00 with the Sur one, losing slot, provider
    and location in a single wrong pick. The ordering was already right, so
    the result now names the earliest token explicitly, and the prompt binds
    the answer to that slot's own provider and location.
    """
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")

    slots = params.result["slots"]
    assert params.result["earliest_token"] == slots[0]["token"]
    earliest = min(slots, key=lambda s: s["start_time"])
    assert slots[0]["start_time"] == earliest["start_time"]
    # The doctor and the site travel with the slot, never across slots.
    assert slots[0]["provider_id"] == earliest["provider_id"]
    assert slots[0]["location_id"] == earliest["location_id"]


async def test_earliest_token_is_absent_when_nothing_is_free(box, monkeypatch):
    empty = AvailabilityResponse.model_validate({**load_fixture("availability"), "slots": []})

    async def _no_slots(**kwargs: Any) -> AvailabilityResponse:
        return empty

    monkeypatch.setattr(box.client, "search_availability", _no_slots)
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
    assert params.result["slots"] == []
    assert params.result["earliest_token"] is None


async def test_slot_results_are_deterministic(box):
    params = await confirm_marta(box)
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
    first = params.result["slots"]
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
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
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
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
    await box.find_availability(params, when_phrase="tomorrow", specialty_name="General practice")
    call = box.client.availability_calls[-1]
    assert isinstance(call["date_from"], date)


# ---- phone hint: caller id is a hint, never identity ------------------------
class PhoneHintClient:
    """Directory stub with configurable matches; records phone lookups."""

    def __init__(self, matches: list[dict[str, Any]] | Exception) -> None:
        self._matches = matches
        self.calls: list[dict[str, Any]] = []

    async def search_directory(self, **kwargs: Any) -> DirectoryResponse:
        self.calls.append(kwargs)
        if isinstance(self._matches, Exception):
            raise self._matches
        return DirectoryResponse.model_validate({"matches": self._matches})


def hint_fixture_matches() -> list[dict[str, Any]]:
    return load_fixture("directory")["matches"]


async def audit_blob(ctx) -> str:
    return ctx._audit_path.read_text(encoding="utf-8")


async def test_phone_hint_resolves_exactly_one_match(box, ctx):
    client = PhoneHintClient(hint_fixture_matches()[:1])  # exactly one patient
    box.client = client
    ctx.from_number = "+34612345678"
    ctx.mark_start_received()

    await box.prepare_phone_hint()

    assert client.calls == [{"phone": "+34612345678"}]
    hint = ctx.phone_hint_match
    assert hint is not None
    assert hint["patient_id"] == "P00042"
    assert hint["given_name"] == "Marta"
    # Protected fields never reach the hint, however the API answered.
    assert "national_id" not in hint
    assert "phone" not in hint
    assert "12345678Z" not in str(hint)
    assert "612345678" not in str(hint)
    # And the audit trail leaks nothing either.
    blob = await audit_blob(ctx)
    assert "612345678" not in blob
    assert "12345678Z" not in blob


async def test_phone_hint_never_enters_the_confirmation_registry(box, ctx):
    """A phone match alone can never pass confirm_patient."""
    client = PhoneHintClient(hint_fixture_matches())
    box.client = client
    ctx.from_number = "+34612345678"
    ctx.mark_start_received()

    await box.prepare_phone_hint()

    assert ctx.patient_candidates == []  # registry untouched
    params = FakeParams()
    await box.confirm_patient(params, patient_id="P00042")
    assert "patient_id not among lookup results" in params.result["error"]
    assert ctx.confirmed_patient is None
    assert ctx.queued_actions == []


async def test_phone_hint_ambiguous_number_greets_generically(box, ctx):
    client = PhoneHintClient(hint_fixture_matches())  # two patients share the line
    box.client = client
    ctx.from_number = "+34600000000"
    ctx.mark_start_received()

    await box.prepare_phone_hint()

    assert ctx.phone_hint_match is None


async def test_phone_hint_client_error_greets_generically(box, ctx):
    client = PhoneHintClient(TimeoutError("api down"))
    box.client = client
    ctx.from_number = "+34612345678"
    ctx.mark_start_received()

    await box.prepare_phone_hint()

    assert ctx.phone_hint_match is None
    blob = await audit_blob(ctx)
    assert '"outcome": "error"' in blob


async def test_phone_hint_skipped_until_start_arrives(box, ctx):
    """No start event within the bounded wait: no lookup, generic greeting."""
    client = PhoneHintClient(hint_fixture_matches())
    box.client = client
    ctx.from_number = "+34612345678"
    # start never arrives

    await box.prepare_phone_hint()

    assert client.calls == []
    assert ctx.phone_hint_match is None


async def test_phone_hint_waits_for_a_late_start(box, ctx):
    """Start arriving inside the 500 ms window still yields the hint."""
    import asyncio

    client = PhoneHintClient(hint_fixture_matches()[:1])
    box.client = client
    ctx.from_number = "+34612345678"

    async def late_start() -> None:
        await asyncio.sleep(0.05)
        ctx.mark_start_received()

    task = asyncio.create_task(late_start())
    await box.prepare_phone_hint()
    await task

    assert len(client.calls) == 1
    assert ctx.phone_hint_match is not None


async def test_phone_hint_skipped_without_caller_id(box, ctx):
    client = PhoneHintClient(hint_fixture_matches())
    box.client = client
    ctx.mark_start_received()
    # from_number stays None: withheld caller id

    await box.prepare_phone_hint()

    assert client.calls == []
    assert ctx.phone_hint_match is None


async def test_phone_hint_skipped_without_api_credentials(box, ctx):
    """An offline host must never be pushed against the Prosper API."""
    client = PhoneHintClient(hint_fixture_matches())
    box.client = client
    box.settings = FakeSettings()
    box.settings.prosper_api_key = ""
    ctx.from_number = "+34612345678"
    ctx.mark_start_received()

    await box.prepare_phone_hint()

    assert client.calls == []
    assert ctx.phone_hint_match is None


# ---- Jev advisory tool: assess_current_turn (Gemini path) --------------------
class FakeJev:
    """Stands in for JevClient; captures the snapshot it is handed."""

    def __init__(self, decision: Any | None = None, error: Exception | None = None) -> None:
        self._decision = decision
        self._error = error
        self.snapshots: list[Any] = []
        self.budgets: list[Any] = []

    async def assess(self, snapshot: Any, cancel: Any = None, timeout_seconds: Any = None) -> Any:
        self.snapshots.append(snapshot)
        self.budgets.append(timeout_seconds)
        if self._error is not None:
            raise self._error
        return self._decision

    async def close(self) -> None:
        pass


def jev_decision(**overrides: Any) -> Any:
    from agent.decision.models import TurnDecision, TurnIntent

    base: dict[str, Any] = {
        "intent": TurnIntent.CANCEL_APPOINTMENT,
        "medical_emergency": False,
        "needs_clarification": False,
        "confidence": 0.9,
        "abstained": False,
        "abstention_reason": None,
        "model": "jev-1.13.0",
        "latency_ms": 12.0,
    }
    base.update(overrides)
    return TurnDecision(**base)


async def test_assess_current_turn_reads_only_the_latest_caller_turn(box, ctx):
    ctx.latest_caller_turn = "Quiero cancelar mi cita del jueves"
    box.jev = FakeJev(jev_decision())
    params = FakeParams()

    await box.assess_current_turn(params)

    snapshot = box.jev.snapshots[-1]
    assert [t.text for t in snapshot.transcript] == ["Quiero cancelar mi cita del jueves"]
    assert len(snapshot.transcript) == 1  # latest turn only, never the whole call
    result = params.result
    assert result["abstained"] is False
    assert result["intent"] == "cancel_appointment"
    # The model gets the answer, not the telemetry: source, model id, latency
    # and token counts buried the one field it can act on, so they now live
    # in the audit only.
    assert set(result) == {
        "intent",
        "medical_emergency",
        "confidence",
        "abstained",
        "message",
    }
    # needs_clarification came back True on every probe, including verdicts
    # at confidence 1.0, so it never reaches the model — only the audit.
    assert "too_ambiguous_to_act" not in result
    assert '"advisory": true' in (await audit_blob(ctx)).lower()


async def test_every_caller_turn_is_read_in_the_background(box, ctx):
    """Jev on the whole call, at no cost to any turn.

    Made a tool, it was never called: 0 invocations across 47 real calls.
    Read on every finalised caller turn instead, the typed verdict is on the
    context before any tool asks for it — and it is paid for while the model
    is already generating, so no caller ever waits for it.
    """
    box.jev = FakeJev(jev_decision())
    box.watch_caller_turns()

    ctx.add_transcript("caller", "quiero cancelar mi cita del jueves")
    await asyncio.sleep(0)  # let the background read run
    for _ in range(20):
        if ctx.latest_decision is not None:
            break
        await asyncio.sleep(0.01)

    assert ctx.latest_decision is not None, "the turn was never read"
    assert ctx.latest_decision["intent"] == "cancel_appointment"
    assert box.jev.snapshots, "the sidecar was never reached"


async def test_background_reads_get_the_wider_budget(box, ctx):
    """The two callers have opposite constraints, so they get two budgets.

    A background read is paid for while the model is already generating, and
    the first assessment of a process measures ~600 ms — a tight budget turns
    the caller's opening sentence into an abstention. A read the model waited
    for is silence on the line and keeps the short default.
    """
    from agent.decision.client import BACKGROUND_TIMEOUT_SECONDS

    box.jev = FakeJev(jev_decision())
    box.watch_caller_turns()
    ctx.add_transcript("caller", "quiero cancelar")
    for _ in range(20):
        if ctx.latest_decision is not None:
            break
        await asyncio.sleep(0.01)
    assert box.jev.budgets[-1] == BACKGROUND_TIMEOUT_SECONDS

    ctx.latest_decision = None
    await box.assess_current_turn(FakeParams())
    assert box.jev.budgets[-1] is None, "a read the caller waits on must not be widened"


async def test_a_new_caller_turn_invalidates_the_old_reading(box, ctx):
    """A verdict describes one utterance; it must never outlive it."""
    box.jev = FakeJev(jev_decision())
    ctx.latest_decision = {"intent": "book_appointment"}

    ctx.add_transcript("caller", "en realidad prefiero cancelarla")

    assert ctx.latest_decision is None or ctx.latest_decision["intent"] != "book_appointment"


async def test_closing_the_toolbox_cancels_pending_reads(box, ctx):
    """No background read may outlive the socket that started it."""
    box.jev = FakeJev(jev_decision())
    box.watch_caller_turns()
    ctx.add_transcript("caller", "hola")

    await box.aclose()

    assert box._assessments == set()
    assert ctx._on_caller_turn is None
    # A transcript arriving after teardown must not resurrect the sidecar.
    ctx.add_transcript("caller", "sigo aqui")
    assert box._assessments == set()


async def test_assess_current_turn_scrubs_known_patient_names(box, ctx):
    ctx.latest_caller_turn = "Hola, soy Marta Ruiz, quiero cancelar"
    ctx.confirmed_patient = {"given_name": "Marta", "first_surname": "Ruiz", "second_surname": "Gómez"}
    box.jev = FakeJev(jev_decision())

    await box.assess_current_turn(FakeParams())

    snapshot = box.jev.snapshots[-1]
    text = snapshot.transcript[0].text
    assert "Marta" not in text and "Ruiz" not in text
    assert "[REDACTED]" in text


async def test_assess_current_turn_abstains_without_caller_text(box, ctx):
    box.jev = FakeJev(jev_decision())
    params = FakeParams()

    await box.assess_current_turn(params)

    assert box.jev.snapshots == []  # sidecar never called on empty state
    assert params.result["abstained"] is True
    # Why it abstained is telemetry for us, not a decision for the model.
    assert "empty_state" in await audit_blob(ctx)


async def test_assess_current_turn_sidecar_crash_cannot_break_the_call(box, ctx):
    ctx.latest_caller_turn = "cancelar por favor"
    box.jev = FakeJev(error=TimeoutError("jev down"))
    params = FakeParams()

    await box.assess_current_turn(params)

    assert params.result["abstained"] is True
    assert "transport_error" in await audit_blob(ctx)
    # The deterministic tools remain fully usable after the abstention.
    assert ctx.queued_actions == []


async def test_assess_current_turn_result_and_audit_are_pii_free(box, ctx):
    ctx.latest_caller_turn = "soy marta, mi telefono es 612345678"
    ctx.confirmed_patient = {"given_name": "Marta", "first_surname": "Ruiz"}
    box.jev = FakeJev(jev_decision())
    params = FakeParams()

    await box.assess_current_turn(params)

    blob = str(params.result) + await audit_blob(ctx)
    assert "612345678" not in blob
    # The sidecar never sees the raw phone either.
    assert "612345678" not in str(box.jev.snapshots[-1].transcript[0].text)
    # The audited decision carries metadata only, never utterance text.
    blob = await audit_blob(ctx)
    assert "soy" not in blob


async def test_assess_current_turn_registered_only_for_gemini_engine(box, ctx):
    box.engine = "cascade"
    assert all(t.__name__ != "assess_current_turn" for t in box.tools())
    box.engine = "gemini_live"
    assert any(t.__name__ == "assess_current_turn" for t in box.tools())


async def test_toolbox_aclose_closes_the_sidecar(box, ctx):
    closed = {"n": 0}

    class ClosableJev(FakeJev):
        async def close(self) -> None:
            closed["n"] += 1

    box.jev = ClosableJev()
    await box.aclose()
    await box.aclose()  # idempotent
    assert closed["n"] == 1
    assert box.jev is None


async def test_a_spoken_insurer_name_is_submitted_as_its_id(box, ctx):
    """The submit enum takes ids; callers say names. Four scored calls died here.

    `Mapfre Salud`, `Sanitas`, `AXA` and `Adeslas` were each queued verbatim
    and each came back 422, so the registration never landed and the case was
    scored missing_record.
    """
    await box.register_new_patient(
        FakeParams(),
        given_name="Paula",
        first_surname="Castro",
        second_surname="Marín",
        national_id="Z0255440F",
        date_of_birth="1972-12-13",
        phone="713273252",
        email="paula.castro71@gmail.com",
        insurer="ASISA",
    )

    assert ctx.queued_actions[-1]["insurer"] == "asisa"


async def test_an_insurer_id_passes_through_untouched(box, ctx):
    await box.register_new_patient(
        FakeParams(),
        given_name="Paula",
        first_surname="Castro",
        second_surname="Marín",
        national_id="Z0255440F",
        date_of_birth="1972-12-13",
        phone="713273252",
        email="paula.castro71@gmail.com",
        insurer="dkv",
    )

    assert ctx.queued_actions[-1]["insurer"] == "dkv"


async def test_an_unknown_insurer_is_refused_while_the_caller_is_still_there(box, ctx):
    """A 422 only surfaces once the call is over, so the guard runs now."""
    params = FakeParams()
    await box.register_new_patient(
        params,
        given_name="Paula",
        first_surname="Castro",
        second_surname="Marín",
        national_id="Z0255440F",
        date_of_birth="1972-12-13",
        phone="713273252",
        email="paula.castro71@gmail.com",
        insurer="Sanitos Premium",
    )

    assert not ctx.queued_actions
    assert "no such insurer" in params.result["error"]
    assert "Sanitas" in params.result["the_clinic_knows"]
